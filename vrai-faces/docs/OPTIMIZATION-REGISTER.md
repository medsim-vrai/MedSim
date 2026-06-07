# VRAI Faces — Optimization Register

A living backlog of **performance optimizations**: ones we *know* will help, ones
that are *very likely*, and *areas to explore* where we don't yet have a specific
lever but should develop one. The point is to look past "make it work" and track,
deliberately, where the next performance gains are — each with an **integration
strategy**, a **documentation plan**, and **estimated costs** so a decision can be
made with eyes open.

> **Scope:** runtime latency, footprint (bundle/model size), memory, battery/thermal,
> startup, and network — across the avatar app (`vrai-faces/packages/core`) and the
> portal speak/listen path. Correctness/visual-fidelity work lives in research briefs
> (`research/RB-*`); product/architecture decisions live in ADRs (`Memory_management.MD`).

---

## How this fits the existing systems

| System | Holds | This register's relationship |
|---|---|---|
| **ADRs** (`Memory_management.MD §7`) | Architecture/product decisions (new deps, data flow, security) | An optimization that adds a dependency or changes data flow **graduates to an ADR** before shipping. |
| **Research Briefs** (`research/RB-*`) | Gated enhancements needing investigation before a go/no-go | An optimization with real unknowns (accuracy, license, sizing) **spawns an RB** first. |
| **Functional Register** (`FUNCTIONAL-REGISTER.md`) | Functional refinements/expansions + the testing-feedback loop | The functional sibling — *behavior* improvements live there, *performance* lives here. |
| **This register** | The performance backlog + the rationale/costs | The cross-cutting list. Quick, low-risk wins ship straight from here; bigger ones point to an RB/ADR. |

**Lifecycle of an entry:**
`Proposed` → (if unknowns) `Researched` via RB → (if a decision) `Decided` via ADR →
`In-progress` → `Shipped` → `Validated` (measured on-device). Low-risk wins skip RB/ADR
and go `Proposed → In-progress → Validated`.

**Planning gate:** the open `OPT-*` backlog is pulled for formal review at the post-Track-4
planning checkpoint (`PLAN-2026-06-07-remaining-development.md`) → triaged + prioritized into
the Track 5+ roadmap, re-run each milestone.

## Legend

- **Area:** STT-latency · TTS-latency · startup · bundle-size · memory · thermal · network · render
- **Confidence:** `Known` (measured / near-certain) · `Likely` (strong prior, unmeasured) · `Exploratory` (worth a look)
- **Status:** `Proposed` · `Researched` · `Decided` · `In-progress` · `Shipped` · `Validated` · `Deferred` · `Watch`
- **Cost dimensions** (estimate each; mark `?` if unknown):
  - **Runtime** — added compute/latency/battery at run time
  - **Size** — added bundle/model/cache bytes (per device + repo)
  - **$** — money (licensing, infra, bandwidth)
  - **Effort** — engineering time (S ≤ ½ day · M ≤ 2 days · L > 2 days)
  - **Risk** — chance it doesn't pan out or destabilizes something (Low/Med/High)

---

## Summary

| ID | Optimization | Area | Confidence | Status | Expected benefit | Size cost | Effort | Risk |
|----|--------------|------|-----------|--------|------------------|-----------|--------|------|
| **OPT-001** | fp16 **encoder** (mixed w/ q8 decoder) on WebGPU | STT-latency | Known | **✅ Validated** | warm ASR ~1855→~1150 ms (−40%), total ~1.15 s ✓ | +16.5 MB (fp16 encoder) | S | Low |
| **OPT-002** | Moonshine short-form ASR (no 30 s pad) | STT-latency | Likely | **Deferred** (prod scaling) | short clips likely <1 s | ~tens of MB (TBD) | L | Med |
| **OPT-003** | STT warm-up inference at load | STT-latency | Known | **✅ Validated** | first take warm (1056 ms), no cold spike | 0 | S | Low |
| **OPT-004** | Bundle code-splitting / lazy heavy chunks | startup/bundle | Known | Proposed | faster cold start; less to cache | −(MB to defer) | M | Low |
| **OPT-005** | Per-capability model shipping (q8 vs fp16) | bundle-size | Likely | Watch | avoid precaching unused variant | up to −76 MB/device | M | Low |
| **OPT-006** | Whisper decoder generation tuning | STT-latency | Exploratory | Proposed | trim decoder tokens (minor) | 0 | S | Low |
| **OPT-007** | Sustained-session thermal headroom (soak harness) | thermal | Known | **✅ Validated** | no throttling: +4% over 12 min / 422 takes | 0 | M | Low |

---

## OPT-001 — fp16 dtype for on-device whisper (WebGPU)

- **Area:** STT-latency · **Confidence:** Known · **Status:** ✅ **Validated** (iPad, 2026-06-05)
- **Result (validated, iPad 11th-gen, 2026-06-05):** warm `asr` **1052 / 1103 / 1303 ms**
  (mean ~1150) vs q8 baseline ~1855 ms → **−40%**; total release→text **~1.15 s**, under the
  1.5 s target with margin. Transcription accuracy maintained; `shader-f16` confirmed on the
  iPad GPU. Mixed precision (fp16 encoder + q8 decoder) loads cleanly.
- **Problem / evidence:** Instrumented iPad takes show **whisper inference is ~99%** of
  release→text latency (rec/decode/resample ≈ 10–25 ms total). Warm ASR ≈ 1.86 s. ASR does
  **not** track clip length (a *longer* clip transcribed *faster*), confirming the encoder
  grinds whisper's fixed **30 s mel window** regardless of how briefly the trainee speaks.
  The bundled model was `q8` (int8) — but **WebGPU has no fast int8 kernel**, so q8 on the
  GPU dequantizes and is often *slower* than fp16.
- **Strategy:** Run the **encoder in fp16 + merged decoder in q8** on WebGPU (mixed
  precision — a supported transformers.js config); q8 everywhere on the WASM/CPU fallback.
  Surface the active dtype in the metrics line (`STT: webgpu·fp16enc·q8dec …`) to confirm.
- **Finding (2026-06-05):** a *full*-fp16 attempt **failed to load** on the iPad —
  `onnx-community`'s **fp16 _merged decoder_ is an invalid ORT model** (its subgraph returns
  `logits` from outer scope → *"This is an invalid model … add an Identity node"*, session
  creation fails). The **encoder** has no such subgraph and is ~99% of the cost, so we fp16
  only the encoder and keep the proven q8 decoder. Lesson logged for OPT-002: validate model
  exports load under onnxruntime-**web** before committing to a variant.
- **Expected benefit:** warm ASR toward/under the ADR-0026 **<1.5 s** target. *Uncertain on
  the iPad's Apple GPU until measured* — fp16 requires the `shader-f16` WebGPU feature
  (Apple Silicon supports it).
- **Integration strategy:** ✅ extend `scripts/setup-assets.mjs` whisper manifest (reproducible
  bundle, local-first per ADR-0001) + per-device dtype in `src/shell/device_stt.ts`. No new
  dependency, no new data flow → **stays inside ADR-0026** (no new ADR needed); note the
  result in ADR-0026.
- **Documentation plan:** this entry → mark `Validated` with the measured number; one-line
  note in ADR-0026 / `docs/DECISION-2026-06-01-hardware-stt.md`; code comments cite OPT-001.
- **Costs:**
  - **Runtime:** none added (swaps the model variant); expected *net faster*.
  - **Size:** **+76 MB** bundled fp16 set (encoder 16.5 MB + merged decoder 59.6 MB). At
    runtime a WebGPU device fetches/caches **only** fp16; a CPU device fetches **only** q8 —
    so per-device *download* is unchanged (~one variant), the cost is repo/server bytes.
  - **$:** none. **Effort:** S. **Risk:** Low (fallback to q8 path intact; accuracy impact
    negligible for tiny).
- **Open questions:** (1) does fp16 on the *encoder* meaningfully cut latency on the Apple
  GPU? — pending iPad measurement. (2) `shader-f16` support: if absent, ORT refuses the fp16
  encoder too → fall back to q8 and OPT-002 becomes the path.

## OPT-002 — Moonshine short-form ASR (no 30 s padding)

- **Area:** STT-latency · **Confidence:** Likely (big win for short clips) · **Status:** Deferred — **for production scaling / if OPT-001 misses target**
- **Problem / evidence:** Whisper's architecture pads every utterance to a **fixed 30 s
  window**, so the encoder does constant work no matter how short the clinical phrase is.
  This structurally **caps** how low whisper latency can go on short PTT.
- **Strategy:** [Moonshine](https://github.com/usefulsensors/moonshine) (Useful Sensors) is
  built for short-form speech — **variable length, no 30 s padding** — so inference scales
  with the *actual* clip. ONNX exports run under onnxruntime-web; expose it behind the
  existing `DeviceSttHandle` interface so whisper↔moonshine is a swap (and A/B-able).
- **Expected benefit:** a ~2–3 s clinical utterance could transcribe **well under 1 s** on
  WebGPU; latency *improves* as phrases get shorter (opposite of whisper). Surest route past
  1.5 s.
- **Integration strategy:** **Research Brief first** (sizing, accuracy vs whisper on clinical
  vocabulary, op/WebGPU support, license) → **ADR** (new model = new asset + license + a new
  `moonshine_stt.ts` adapter) → bundle via `setup-assets.mjs` behind a capability/feature flag.
- **Documentation plan:** `research/RB-00X_moonshine-stt.{html,pdf}` → ADR-00XX → this entry
  to `Validated` with the comparison table.
- **Costs:**
  - **Runtime:** expected *lower* than whisper for short clips; verify cold-load.
  - **Size:** model **TBD** (moonshine-tiny ≈ 27 M params, base ≈ 61 M; quantized likely tens
    of MB — confirm in the RB).
  - **$:** none expected. **Effort:** **L** (new adapter + eval harness + accuracy comparison).
  - **Risk:** **Med** — accuracy on clinical terms, ONNX/WebGPU op coverage, **license must be
    confirmed permissive before bundling** (research question, do not assume).
- **Trigger:** scaling to the production fleet to maximize performance; or immediately if
  OPT-001 doesn't reach <1.5 s on target hardware.

## OPT-003 — STT warm-up inference at load

- **Area:** STT-latency (first-take) · **Confidence:** Known · **Status:** ✅ **Validated** (iPad, 2026-06-05: first take **1056 ms** warm, no cold spike; then 856 / 1200 ms). Effect is modest on this GPU (it warms fast) but removes cold-spike risk.
- **Problem / evidence:** First PTT after load measured **2152 ms** vs ~1900 ms warm — ~250 ms
  is one-time WebGPU shader/pipeline compilation on the first inference.
- **Implemented (2026-06-05):** one silent 16 kHz inference after model load (non-fatal,
  backgrounded). `isReady()` now flips true only *after* warm-up, so the panel showing
  "ready" guarantees a warm first take. **Validate:** first take after a fresh reload sits in
  the warm range (~1050–1150 ms) with no cold spike. Trade-off: "ready" appears ~1 s later
  (the warm-up cost moves to load time, off the PTT critical path).
- **Strategy:** after the pipeline loads (already warmed at boot), run **one dummy inference
  on a short silent buffer** so the trainee's first real take is already warm.
- **Integration strategy:** a few lines in `device_stt.ts` `loadAsr()` post-load. No ADR.
- **Documentation plan:** this entry → `Validated`; code comment cites OPT-003.
- **Costs:** **Runtime:** +1 background inference at load (~2 s, off the critical path; battery
  negligible). **Size:** 0. **$:** 0. **Effort:** S. **Risk:** Low.
- **Note:** improves the *first* take only; does **not** move steady-state — pair with OPT-001.

## OPT-004 — Bundle code-splitting / lazy heavy chunks

- **Area:** startup / bundle-size · **Confidence:** Known (build warns) · **Status:** Proposed
- **Problem / evidence:** `pnpm build` warns chunks >500 kB: **kokoro 2.2 MB**, three 545 kB,
  transformers 546 kB. Kokoro (TTS) is only needed when the avatar *speaks*.
- **Strategy:** confirm heavy libs stay **dynamically imported** (tts/emotion/stt already are);
  add `build.rollupOptions.output.manualChunks` to split vendor bundles; only then adjust the
  warning limit. Keep the app shell small for fast first paint.
- **Integration strategy:** vite config + audit dynamic-import boundaries. No ADR.
- **Documentation plan:** this entry; comment in `vite.config`.
- **Costs:** **Runtime:** none (defers load). **Size:** shifts MB off the critical path.
  **Effort:** M. **Risk:** Low (existing dynamic-import pattern proven).

## OPT-005 — Per-capability model shipping (q8 vs fp16)

- **Area:** bundle-size / repo · **Confidence:** Likely · **Status:** Watch
- **Problem:** bundling q8 (41 MB) + fp16 (76 MB) = **116 MB** of whisper assets in the repo/
  server. At runtime each device fetches only the variant it uses, so per-device *download* is
  fine — but if we ever add a **precache manifest** (PWA install), it must precache only the
  capability-matched variant, not both.
- **Strategy:** capability-gate any precache; optionally build-time variant bundles for prod.
- **Integration strategy:** SW precache logic / build profiles. No ADR.
- **Costs:** **Size:** up to −76 MB/device if precache is added naively. **Effort:** M. **Risk:** Low.
- **Trigger:** before enabling full-offline precache for the production fleet.

## OPT-006 — Whisper decoder generation tuning

- **Area:** STT-latency (decoder) · **Confidence:** Exploratory · **Status:** Proposed
- **Problem:** the autoregressive decoder generates tokens; clinical phrases are short.
- **Strategy:** after OPT-001 reveals the encoder/decoder split, consider `max_new_tokens`
  caps / generation tuning (timestamps already off). Likely minor vs the encoder.
- **Costs:** trivial. **Effort:** S. **Risk:** Low. Revisit once the split is measured.

## OPT-007 — Sustained-session thermal headroom

- **Area:** thermal / sustained latency · **Confidence:** Known · **Status:** ✅ **Validated** (iPad, 2026-06-05)
- **Problem:** ADR-0032 pilot gate — confirm no GPU throttling / latency creep over a sustained session.
- **Tool:** `src/shell/stt_soak.ts` (debug-only, `?debug`) — runs whisper back-to-back on a fixed silent
  buffer, tracks baseline (first 2 min) vs recent median, flags creep >15% as throttling. Reusable for the
  Galaxy Tab S9 head-to-head.
- **Result (iPad 11th-gen, 2026-06-05):** **422 takes over 12:08 · base 716 ms → end 742 ms = +4% · ✓ no
  throttling.** (soakStep runs on silence, so its absolute ~716 ms is below real-speech PTT ~1050 ms — the
  decoder emits fewer tokens; the soak measures the relative thermal *creep*, which is flat.) If creep ever
  appears on other hardware, consider duty-cycling or a lower-power dtype under sustained load.
- **Costs:** measurement only. **Effort:** M. **Risk:** Low (validated).

---

## Exploration areas (no concrete lever yet — develop a strategy)

These are where future performance work is *likely* but we don't have a specific OPT yet.
Promote to a numbered OPT (and RB/ADR if needed) when investigated.

- **Streaming / partial STT** — start inference while recording, or show interim text, to cut
  *perceived* latency below the inference floor. (Pairs with whatever ASR we land on.)
- **TTS speak-path latency** — measure portal ElevenLabs synth + on-device Kokoro end-to-end;
  it's the *other* big link in the bedside loop (STT → AI turn → TTS).
- **Translucent shader / render cost** at full tablet resolution and multi-patient scenes.
- **Three.js memory churn** on re-pair / skin swap (resource registry already centralizes
  disposal — quantify leaks over long sessions).
- **AI-turn latency** (portal `/listen` → reply) — the largest link in the loop on most takes;
  worth profiling so STT tuning is spent where it matters.

---

## Adding an entry

1. Grab the next `OPT-NNN`. Fill **Area, Confidence, Status, Problem/evidence, Strategy,
   Expected benefit, Integration strategy, Documentation plan, Costs**.
2. If there are real unknowns → write a `research/RB-*` brief first. If it adds a dependency
   or changes data flow/security → it needs an **ADR** before `Shipped`.
3. Add a row to the **Summary** table.
4. On ship, measure on-device and move to `Validated` with the number. Keep costs honest —
   if an estimate was wrong, correct it (that's the value of the register).
