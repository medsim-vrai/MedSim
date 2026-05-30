# VRAI Faces — Plan: Re-secure the device voice + Speech-driven facial animation

**Date:** 2026-05-30 · **Author:** build session · **Strategy:** ROADMAP §4
(research brief → park against a phase → run in Cowork → ADR → drop-in behind
existing seams). This plan adds **Phase 6** (re-secure) and **Phase 7**
(speech-driven animation) to `docs/ROADMAP.md`.

> Two workstreams the operator asked for, in their words:
> 1. **"Add back the security"** — replace the cloud-STT push-to-talk *stopgap*
>    (ADR-0025) with the PHI-safe on-device path, and re-assert local-first.
> 2. **"Add the animation to the skinned face driven by the prompts and speech
>    output of the encounter character"** — make the avatar visibly lip-sync +
>    emote from the character AI's spoken lines.

---

## 0. Why these are gated (and not built inline)

Both depend on **maturing/heavy capabilities** that the project rule says to
research first, not bolt on: on-device speech recognition (Workstream A) and an
ARKit-52 blendshape-delta rig (Workstream B). Both already have authored briefs:

| Brief | Enhancement | Gates | Status |
|---|---|---|---|
| **RB-001** | Real ARKit-52 blendshape rig (vs. the 4-shape procedural basis) | Phase 1.2 / **Phase 7** | Open — ready to run |
| **RB-002** | On-device voice (name wake-word + trainee STT) | ADR-0024 / **Phase 6** | Open — ready to run |

The discipline: keep authorized, local-first work moving; run each brief in
Claude Cowork when desired; convert the result to an ADR; drop the engine/asset
in behind seams that are **already in place**.

---

## 1. What is already built (the seams we drop into)

**Speech → animation drive is DONE end-to-end** (ROADMAP Phases 2–4, "loop
closed"). Confirmed by reading the modules:

- `shell/speechConsumer.ts` — a `VRAISpeechFrame` drives: `emotion →
  animation_runtime.setEmotion` (cross-fade); `text → tts_provider.speak
  (Kokoro) → audio_pipeline`; `audio_pipeline.onViseme → animation_runtime`
  (energy-derived visemes, ADR-0015 native-vs-derived seam).
- `animation_runtime.tick()` — sums **viseme + emotion + idle** into a
  pre-allocated `Float32Array(52)`, clamps, writes `morphTargetInfluences` on
  every attached mesh. `Resumable` snapshot/restore intact.
- `emotion_driver` — JSON blendshape weights (lexicon active; transformers.js
  model wired but deferred/unbundled, ADR-0019).
- Portal reply loop — `POST /api/face/<id>/listen` (this session) → character AI
  turn → `push_speech` → `VRAISpeechFrame` over `wss`.

**The gap is the deformation basis, not the plumbing:**

- `mesh_builder` **fallback head-proxy** (`impl/create.ts:buildBaseGeometry`)
  allocates **52 ZERO-displacement** morph attributes → influences change but
  **no vertex moves → animation is invisible**. This is what the tablet shows
  today (the "egg").
- `mesh_builder` **real MediaPipe path** (`impl/face_topology.ts`) applies the
  **procedural `morph_basis.ts`** — but only **4 non-zero shapes** (`jawOpen`,
  `mouthSmileLeft/Right`, `browInnerUp`); all eye/other shapes are zero.
- Full, accurate expression + viseme set = the **ARKit-52 rig (RB-001)** — the
  ROADMAP's named *"biggest single unblock: turns the avatar from 'right shape'
  into 'actually emotes/speaks.'"*

**Security posture relaxed this session (to unblock live testing):**

- **ADR-0025** allows the browser cloud Web Speech API for PTT/name-trigger,
  **off by default**, "not for PHI" — explicitly a stopgap, superseded by RB-002.
- `POST /api/face/<id>/listen` is **no-auth** (device-origin trust, like
  binding/speak); trainee text reaches the character AI.
- HTTPS is now the secure-context baseline (dev cert), but it's **informal** (no
  ADR; gated only on cert presence).

---

## 2. Workstream A — Re-secure the device voice  ·  **Phase 6**

**Goal.** Trainee speech is recognized **on the device**; **no microphone audio
ever leaves the tablet**; the cloud-STT stopgap is retired; ADR-0001 (local-first)
and ADR-0014 (PHI fail-closed) are re-asserted; the HTTPS/device-trust posture is
formalized.

**Gate.** On-device ASR + wake-word maturity/footprint on iPad-class hardware →
**RB-002** (authored).

### Steps

- **A1 · Run RB-002 in Cowork.** Deep-research the two engines: (a) name
  wake-word (lightweight keyword-spotter vs. rolling tiny-STT match), (b) PTT STT
  (transformers.js Whisper tiny/base WASM+WebGPU vs. Chrome on-device
  `SpeechRecognition processLocally` vs. a Capacitor-native ASR). Output: ranked
  options with the measured criteria below + a go/no-go.
- **A2 · ADR + assets.** Record the engine/model decision in
  `Memory_management.MD §7`; add the model to `VRAI_Faces_Tools_Resources.xlsx`
  + `setup:assets` (lazy, **never at boot**), per the new-dependency rule.
- **A3 · Build the on-device modules.** `name_trigger` (emits "addressed" when
  the character's name is heard) + `device_stt` (PTT audio → text), both
  **on-device, fail-closed** (no detection ⇒ no action; raw audio never
  transmitted). They reuse the **existing `device_voice.ts` UI** (the toggle, the
  hold-to-talk button, the editable wake-name) — swap the engine behind it.
- **A4 · PHI-safe routing.** Transcribed text → the existing
  `/api/face/<id>/listen` → character AI. Ensure `trainee_input` passes the
  **ADR-0014 fail-closed PHI classifier** before any non-BAA cloud call (the
  text→reply loop already exists; this gates it correctly).
- **A5 · Retire the stopgap.** Make the `device_voice.ts` **cloud** path
  dev-only behind an explicit build flag (or remove it); mark **ADR-0025
  superseded** by the A2 ADR. Default device voice = on-device.
- **A6 · Formalize the security posture (ADR).** One ADR covering: the
  **secure-context (HTTPS) requirement** for WebGPU + mic + `crypto.subtle` on a
  tablet (so `face_ingest`'s non-crypto fallback becomes a true fallback, not the
  norm); the **dev-cert workflow** (`scripts/make-dev-cert.sh`); and the
  **device-endpoint trust model** — today the `/api/face/*` device routes are
  no-auth (LAN trust); decide whether to add a **per-session device token**
  (minted at QR time) so a stray LAN client can't drive an avatar or spend AI.

### Acceptance criteria (from RB-002 — hard gates in **bold**)

| Criterion | Target |
|---|---|
| Microphone audio leaves the device | **Never** (ADR-0001/0014) |
| Wake-word false-accept | < 1 / 10 min idle |
| Wake-word detect latency | < 500 ms |
| PTT utterance → text | < 1.5 s after release |
| STT word error rate (clinical phrases) | < 12% |
| Model footprint / cold load | ≤ ~80 MB / ≤ ~5 s |
| Sustained cost | no thermal throttle over 20 min |

### ADRs this workstream produces
On-device voice engine (A2) · Secure-context + device-trust posture (A6) ·
ADR-0025 marked superseded (A5).

---

## 3. Workstream B — Speech-driven facial animation  ·  **Phase 7**

**Goal.** On the device, the **skinned face visibly animates** from the
character AI's output: **lip-sync** from the spoken audio, **expression** from
the frame's emotion, plus **idle** blink/gaze — on the assigned skin.

**Insight.** The *drive* is built; the *deformation basis* is the gap. So this
workstream has an **ungated near-term win (B0–B1)** and a **gated fidelity
upgrade (B2–B6, RB-001)**.

### Steps

- **B0 · Make motion visible NOW (ungated).** Two parts:
  - **B0a — light up the real path on the device.** Bundle the MediaPipe
    `face_landmarker.task` + canonical topology JSON as **lazy assets**
    (`setup:assets`); confirm detection on a real **assigned skin** (a face
    photo) over the device path, so the geometry carries the procedural
    `morph_basis` instead of the zero-morph head-proxy.
  - **B0b — animate the fallback too (optional).** Apply the 4-shape procedural
    basis to `buildBaseGeometry()` so even the no-face head-proxy flaps its jaw +
    smiles + raises brows. Result: **visible (coarse) jaw lip-sync + emotion on
    the device today**, no RB-001 needed.
- **B1 · Verify the chain on real hardware.** The unit seam test
  (`speech_frame_to_runtime.test.ts`) passes; verify on the tablet over the
  `/listen` + speak path: a spoken `VRAISpeechFrame` → jaw moves with the audio
  energy, emotion shifts the expression, idle blink runs. Measure the §5 budgets
  (audio→viseme, viseme→frame) **on-device**, not just in unit tests.
- **B2 · Run RB-001 in Cowork.** Source/author an **ARKit-52 deformation basis**
  on the 468-vertex topology (deformation transfer vs. a licensed rig vs. a
  procedural authoring pass). Output: ranked options + a go/no-go (watch
  licensing — gated source).
- **B3 · ADR + rig asset.** Record the rig decision; bundle the basis as a
  **lazy data asset**; replace `morph_basis.ts`'s 4 shapes with the full 52 so
  **every** influence (visemes + expression) deforms the real face.
- **B4 · Upgrade lip-sync fidelity.** Move from **energy-derived** jaw visemes to
  **phoneme/viseme-mapped** mouth shapes: map Kokoro's phoneme timing → ARKit
  viseme morphs through the **existing ADR-0015 `setVisemeSource` seam** (native
  vs. derived). Energy-derived stays the floor when phonemes are unavailable.
- **B5 · `avatar_exporter` morph baking** (Phase 1.3, *blockedBy B3*). Add the
  per-primitive `targets[]` block now that real deltas exist; round-trip the GLB
  morphs.
- **B6 · Emotion expressiveness.** With the real rig, map `emotion_driver`'s JSON
  weights to ARKit expression morphs (brow/eyes/mouth) so clinical affect
  (pain/fear/relief) reads on the face. The transformers.js GoEmotions model
  (ADR-0019, gated) drops in later for paraphrase-robust emotion — no code change.

### Acceptance criteria
On the device, on an assigned skin: a spoken line **visibly moves the mouth in
sync** (within the §5 audio→viseme budget); the **emotion of the line shows** on
the face; **idle blink/gaze** runs; the real MediaPipe path (not the zero-morph
head-proxy) is active.

### ADRs this workstream produces
ARKit-52 rig source/asset (B3) · phoneme→viseme lip-sync mapping (B4, if it
warrants its own decision).

---

## 4. Sequencing, dependencies, parallelism

```
        ┌─ A1 RB-002 (Cowork) ─ A2 ADR/assets ─ A3 modules ─ A4 PHI route ─ A5 retire stopgap ─ A6 security ADR
 NOW ───┤
        └─ B0 visible motion (ungated) ─ B1 device verify ─┐
                                                           ├─ B2 RB-001 (Cowork) ─ B3 rig ─ B4 visemes ─ B5 export ─ B6 emotion
        (B2 can start in parallel with B0/B1) ─────────────┘
```

- **A and B are independent** — run in parallel.
- **B0–B1 deliver visible animation fast**, without waiting on any research gate.
- **A1 (RB-002) and B2 (RB-001)** are the two Cowork research kicks; both can be
  launched immediately and run while B0/B1 proceed.
- **Critical path to a believable + secure tablet demo:**
  `B0 + B1` (motion now) → `A` (on-device voice) → `RB-001` (full-fidelity rig).
- Lowest-effort, highest-visible-impact first move: **B0** (light up the real
  MediaPipe path + animate the fallback) — turns the static egg into a talking,
  emoting head with zero gated dependencies.

---

## 5. Risks & mitigations

- **On-device ASR perf/maturity on iPad** → RB-002 measures it before we commit a
  model; Capacitor-native ASR is a fallback engine option.
- **Rig authoring effort / licensing** (RB-001 names licensing as the gate) →
  research ranks build-vs-license; the procedural basis (B0) keeps motion shipping
  meanwhile.
- **WebGPU vs WebGL2 parity** → HTTPS gives WebGPU on the tablet (skin renders);
  keep the WebGL2 fallback honest so a non-WebGPU device degrades, not breaks.
- **PHI fail-closed correctness** (ADR-0014) when trainee text → cloud AI →
  re-verify the classifier gates `/listen` before any non-BAA call.
- **Secure-context operational friction** (cert trust on each tablet) → documented
  in BUILD_STATE; A6 formalizes it; consider shipping the CA via MDM for fleets.

---

## 6. Deliverables checklist

- [ ] ROADMAP §2: add **Phase 6** (re-secure) + **Phase 7** (animation); §4 table: add RB-002.
- [ ] Cowork run of **RB-002** → ADR (engine) → `name_trigger` + `device_stt` → retire ADR-0025 stopgap → security/HTTPS ADR.
- [ ] **B0** (ungated): bundle MediaPipe assets + animate the fallback → visible motion on the device.
- [ ] **B1**: device-verify the speech→viseme/emotion/idle chain + §5 budgets.
- [ ] Cowork run of **RB-001** → ADR (rig) → full ARKit-52 basis → phoneme visemes → `avatar_exporter` baking → emotion mapping.
- [ ] Each gated decision recorded as an ADR in `Memory_management.MD §7`; new models on the tools sheet (lazy).

> **Confirm before building the gated pieces.** A3/B3 depend on the RB-002 /
> RB-001 outcomes — run the briefs first, then ADR, then drop in. B0/B1 and the
> A4/A6 hardening can proceed now without a research gate.
