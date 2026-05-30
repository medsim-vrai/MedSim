# ADR-0019 — On-device emotion-inference engine for `emotion_driver`

- **Status:** ACCEPTED 2026-05-29 — recorded in `Memory_management.MD §7` as ADR-0019. Implementation in Phase 3 (see `docs/ROADMAP.md`).
- **Date:** 2026-05-29
- **Module:** `emotion_driver`
- **Supersedes / refines:** the deferral baked into `emotion_driver/impl/create.ts`
- **Relates to:** ADR-0001 (local-first), ADR-0005 (JSON weights, not free text),
  ADR-0014 (PHI guardrail), ADR-0009 (WebGPU + WASM fallback)

> This is the long-form ADR (`docs/` per §7 convention). **RATIFIED 2026-05-29**
> — the one-line entry is now recorded in `Memory_management.MD §7` (ADR-0019).
> Exact model id, bundle budget, and cloud opt-in are settled when Phase 3 is built.

---

## Context

`emotion_driver.inferBaseline(input) → { label, weights }` is the module that
turns a character's utterance into a target facial **mood** (ARKit-52 blendshape
weights). Its contract (`src/types/emotion_driver.ts`) and the Stack of Record
(`Memory_management.MD §2`) both already *name* the intended engine:

> "Runs locally via transformers.js by default; cloud Claude is allowed if the
> scenario opts in."

But the shipped implementation is a deliberate stand-in: a **deterministic
lexicon classifier** (six clinically-salient moods — pain, fear, anger, sad,
drowsy, relieved — matched by keyword). It was chosen because it needs no model,
adds **zero dependencies**, and is **PHI-safe by construction** (nothing leaves
the device). The impl header says as much, and flags the real engine as deferred
"behind its ADR." This is that ADR.

The lexicon is brittle in the ways a keyword matcher always is: it misses
paraphrase, negation ("the pain is *gone*"), intensity gradation, and any
utterance that doesn't contain a listed token. For a patient-simulation avatar
whose believability is the entire product, "neutral because no keyword hit" is a
visible failure.

Two facts from this session matter to the decision:

1. **The cross-fade just landed.** `animation_runtime.setEmotion(weights, easeMs)`
   now eases `emotionCurrent → emotion` over a window (smoothstep). So
   `inferBaseline` produces a *target* and the runtime absorbs the transition
   smoothly — the inference cadence (per-utterance) is fully decoupled from the
   60 Hz render loop, and a few tens of ms of model latency is invisible.
2. **The budget is friendly.** `§5` budgets the **emotion update at 10 Hz**, and
   baseline inference is per-utterance, not per-frame. There is real headroom for
   an on-device model that the per-frame paths (≤16 ms) would never tolerate.

A new third-party runtime dependency requires both an ADR **and** a line in
`VRAI_Faces_Tools_Resources.xlsx` ("when in doubt, write the ADR first").

## Decision (proposed)

Adopt **transformers.js** (`@huggingface/transformers`, the maintained successor
to `@xenova/transformers`) as the on-device emotion-inference engine behind
`emotion_driver.inferBaseline`, running entirely **local** on the WASM backend
with the **WebGPU** backend used when ADR-0009 feature-detection reports it.

The driver becomes a **hybrid**, not a wholesale replacement:

- A small **quantized text-classification model** (int8, GoEmotions-class —
  e.g. a DistilBERT/MiniLM fine-tune) yields a valence/arousal + general-emotion
  read of the utterance.
- The existing **lexicon stays** as (a) the zero-model fallback when the model is
  absent or warmup fails, and (b) the authoritative source for the
  **clinically-specific affects the general models do not have a label for** —
  notably *pain* and *drowsy/lightheaded*, which are not standard NLP emotion
  classes but are the most diagnostically important in a patient sim.
- The model's output maps onto the **same six mood weight-sets** already authored
  in the lexicon, so the ARKit weight vocabulary and `§4`/ADR-0005 JSON-only
  output contract are unchanged. `warmup()` loads the model once; `inferBaseline`
  stays `async` (already is).

Cloud Claude remains a **per-scenario opt-in** future path, explicitly **out of
scope for this ADR** and gated by ADR-0014's fail-closed PHI classifier if it
ever ships. The default and the only path enabled by this ADR is on-device.

## Why this option

| Option | Quality | Local-first (ADR-0001) | PHI surface (ADR-0014) | Cost / latency | Verdict |
|---|---|---|---|---|---|
| **A. transformers.js on-device (proposed)** | Good — generalizes past keywords | ✅ stays on device | ✅ none (nothing leaves) | One-time model download + warmup; per-utterance ms on WASM/WebGPU | **Chosen** |
| B. Lexicon only (status quo) | Poor — brittle, no paraphrase/negation | ✅ | ✅ | ~0 | Rejected as the *ceiling*; kept as the *floor* (fallback) |
| C. Cloud LLM (Claude) for emotion | Best | ❌ network dependency | ⚠️ adds a free-text egress surface | Per-utterance network + token cost | Deferred — conflicts with local-first; revisit as opt-in |
| D. Bundle a hand-rolled tiny classifier | Medium | ✅ | ✅ | Training/maintenance burden, no ecosystem | Rejected — reinvents transformers.js for less |

Option A is the only one that raises the quality ceiling **without** breaking
the local-first posture that ADR-0001 treats as non-negotiable.

## Consequences

**Positive**
- Real generalization: paraphrase, intensity, and negation handling the lexicon
  can't do; fewer "neutral" misfires on in-character speech.
- No change to module boundaries or the `inferBaseline` contract — swapping the
  body is contract-preserving (the impl header already promised this).
- Pairs naturally with the new cross-fade: smoother, model-driven baselines.

**Negative / risks (the honest part)**
- **Bundle weight.** A quantized DistilBERT-class model is tens of MB on disk —
  a real cost for a local-first tablet bundle. Mitigation: int8 quantization,
  lazy-load in `warmup()` (not at boot), and cache via the service worker.
- **Model-coverage gap.** Off-the-shelf emotion models have no *pain* or *drowsy*
  label. Mitigation: the hybrid above — lexicon overrides for clinical affects;
  the model refines valence/arousal and the general moods. This gap is the single
  biggest reason this is "proposed," not "obvious."
- **Determinism.** A model is less auditable than a keyword table; QA fixtures
  must pin model + version, and the soak/regression suite should snapshot a small
  labelled utterance set. ADR-0005's JSON-only output keeps it lint-checkable.
- **New dependency.** Requires a row in `VRAI_Faces_Tools_Resources.xlsx` and a
  pinned version (transformers.js + the specific model id + revision hash).
- **WASM/WebGPU init cost.** First inference after warmup pays a compile cost;
  `warmup()` must be called off the hot path (it already exists for this purpose).

## Open implementation questions (settle during Phase 3)

Ratified 2026-05-29 with the **hybrid** approach, so #3 is decided. The rest are
Phase-3 implementation tuning, not ratification blockers:

1. **Model pick.** Confirm a specific quantized model id + revision (GoEmotions
   DistilBERT vs a smaller MiniLM) — drives bundle size and the mood mapping.
2. **Bundle budget.** Is tens-of-MB acceptable in the local-first tablet build,
   or should the model be an optional download fetched on first launch?
3. ~~Clinical affects~~ — **DECIDED: hybrid** (lexicon retains *pain*/*drowsy*).
4. **Cloud path.** Ship the Claude opt-in day-1 behind ADR-0014, or keep it a
   v1.1 flag? (Tracked with the §9 cloud question — Phase 0 decision 3.)

## Recorded in `Memory_management.MD §7` (ratified 2026-05-29)

```
- **ADR‑0019 | 2026‑05‑29 | Emotion driver uses transformers.js ON‑DEVICE (hybrid: small quantized GoEmotions‑class model + lexicon fallback/clinical override) — cloud Claude stays opt‑in per scenario** | Lexicon stand‑in can't handle paraphrase/negation/intensity, but local‑first (ADR‑0001) forbids a cloud default and off‑the‑shelf models lack clinical affects (pain/drowsy) | Adds a pinned transformers.js dep + a model in the tools sheet; model loads in `warmup()` not at boot; lexicon retained as the zero‑model fallback; output stays JSON weights (ADR‑0005); any cloud path remains gated by the ADR‑0014 fail‑closed PHI classifier.
```

> ✅ This line is now in `§7`. The pinned transformers.js dependency + model
> entry (with the tools-sheet row) land in Phase 3, per ADR-0001 local-first.
