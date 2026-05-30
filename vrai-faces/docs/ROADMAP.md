# VRAI Faces — Path to Completion

Status review + dependency-ordered module path. Scope = the `vrai-faces` avatar
subsystem (not the V7 carryover). "Done" is defined by `Memory_management.MD §1`
(mission) and §5 (latency budgets). Dated 2026-05-29.

---

## 1. Status snapshot

Legend: ✅ real/complete · 🟡 works but placeholder/approx · 🟦 scaffold · ⬜ not started

| Area | State | What's real today | The gap to "done" |
|---|---|---|---|
| **face_ingest** | ✅ | 512² crop, EXIF, alpha-strip, SHA-256 cache key | real-path coverage only via e2e (needs a portrait fixture) |
| **mesh_builder** | 🟡 | Real MediaPipe landmark→geometry path + sphere fallback; topology asset bundled | live path **never browser-verified**; morph basis is a **procedural approximation (4 of 52 shapes)** |
| **shader_translucent** | ✅ | TSL Fresnel rim, §4 anchor table, uniform-only updates | — |
| **avatar_exporter** | 🟡 | Hand-rolled GLB/VRM, opacity baked (`KHR_materials_transmission`) | **morph-target baking deferred** — no `targets[]` block until mesh_builder emits real deltas |
| **animation_runtime** | ✅ | viseme + emotion cross-fade + idle blend + diag | — |
| **audio_pipeline** | ✅ | Web Audio graph, gapless schedule, energy→jawOpen fallback, iOS prime (ADR-0008) | native-vs-derived viseme **gating (ADR-0015) not wired**; browser paths untested in jsdom |
| **tts_provider** | 🟡 | Tier routing + **PHI guardrail (ADR-0014) real & tested**; synthetic voicing stand-in | **no real engines** (Azure/ElevenLabs/Cartesia + local Kokoro/Piper); failover state machine (ADR-0013) untested |
| **emotion_driver** | 🟡 | Keyword-lexicon classifier → JSON weights (ADR-0005), PHI-safe | **real engine gated on ADR-0019** (transformers.js, still *Proposed*) |
| **idle_motion** | ✅ | deterministic blink/saccade/sway | — |
| **medsim_adapter** | 🟡 | BroadcastChannel (same-origin) + frame/character parsing (fail-closed) | **WebSocket (cross-app tablet) deferred**; real MedSim character **schema wiring** open (§9) |
| **memory_state** | ✅ | IndexedDB pause/resume, PHI-free, e2e-covered | IDB-unavailable fallback stub |
| **diagnostic_panel** | ✅ | dev DOM overlay, PHI-safe (message-only) | — |
| **App shell / renderer / slider** | ✅ | full pipeline wired in `main.ts`; WebGPU+WebGL2; demo synth portrait | demo portrait → swap for `medsim_adapter` binding |
| **perf / latency_meter** | 🟡 | per-stage budget marks → diag | no aggregation; **§5 budgets never validated**; diag is console-only |
| **workers (OffscreenCanvas)** | 🟦 | message protocol defined | renderer offload **not implemented**, never invoked |
| **e2e tests** | 🟡 | `qr-launch` + `pause-resume` are real | **`soak.spec.ts` is a placeholder**; no real portrait PNG fixture |
| **Capacitor (iOS/Android)** | 🟦 | real `capacitor.config` + scripts | **empty native dirs**; no `cap add`, no native build/CI |
| **CI** | ⬜ | — | no `.github/workflows` gating typecheck/no-any/test/build |

**Bottom line:** the *architecture and plumbing are essentially complete and green*
(72 unit tests, full pipeline wired). What remains is **swapping 4 placeholders for
real engines/data, wiring MedSim, and hardening for ship.**

---

## 2. The path (dependency-ordered)

### Phase 0 — Unblock: ratify decisions  ·  _cheap, gates Phases 2–3_
Resolve the gated ADRs + `§9` product questions so engine work isn't blocked:
- **ADR-0019** (emotion engine: transformers.js on-device) — ratify or revise.
- **Local-TTS engine ADR** — pick Kokoro-WebGPU vs Piper-WASM (+ tools-sheet line).
- **§9 calls:** cloud TTS day-1 vs v1.1 flag · default "ghost" color · HeadTTS voice bundle · how the portal lists launchable characters · pause/resume across device restarts.

### Phase 1 — Real avatar (visual fidelity)  ·  _critical path_
1. **mesh_builder — browser-verify the live MediaPipe path** end-to-end (add the real portrait fixture; confirm `detect()` yields 478 landmarks + a real face mesh in Chrome).
2. **Blendshape-delta rig** — replace the procedural morph basis (`morph_basis.ts`, 4 shapes) with a real ARKit-52 deformation basis on the 468-vertex topology (source/author a rig; bundle as a data asset).
3. **avatar_exporter — morph-target baking** — add the per-primitive `targets[]` block now that real deltas exist; round-trip test the GLB morphs. *(blockedBy #2)*

### Phase 2 — Real speech (voice + lip-sync)  ·  _blockedBy Phase 0_
1. **tts_provider — local fallback engine** (Kokoro/Piper per Phase 0) — the local-first default; replaces synthetic voicing offline.
2. **tts_provider — cloud tiers** (Azure HD primary w/ native visemes; ElevenLabs/Cartesia) behind the BAA guardrail; implement + test the **failover state machine** (ADR-0013).
3. **audio_pipeline — ADR-0015 viseme gating** — use provider-native visemes when present; HeadAudio-derived bridge otherwise.

### Phase 3 — Real emotion  ·  _blockedBy Phase 0 (ADR-0019)_
1. **emotion_driver — on-device engine** (transformers.js, hybrid: model + lexicon fallback + clinical-affect override). Keep ADR-0005 JSON-only output; deterministic QA fixtures.

### Phase 4 — MedSim integration (close the loop)
1. **medsim_adapter — real character schema** — Zod against `medsim_v8/schemas/` (confirm path, §9); bind real portraits/personas.
2. **medsim_adapter — WebSocket transport** — cross-app tablet path (reconnect + `seq` dedup), beyond same-origin BroadcastChannel.
3. **portal — speak/drive path** — push `VRAISpeechFrame`s to the avatar; launchable-character list.

### Phase 5 — Hardening & ship  ·  _blockedBy Phases 1–4_
1. **e2e** — real portrait fixture; flesh out `soak.spec.ts` (heap/FPS/worklet-underrun over 5 min); the `fixture.spec.ts` full-pipeline run.
2. **perf** — validate §5 budgets with `latency_meter`; optional telemetry export.
3. **OffscreenCanvas worker** — finish renderer offload (optional, perf only).
4. **Capacitor** — `cap add ios/android`, `Info.plist` `UIBackgroundModes=audio` (ADR-0006), build `.ipa`/`.apk`; verify pause/resume across device restarts.
5. **CI** — `.github/workflows`: typecheck + check:no-any + test + build gates.

---

## 3. Critical path vs. full ship

- **Believable local-first demo** = Phase 0 → 1 → 2.1 (local voice) → 3 → 4.
  (Real per-identity face that emotes + speaks with lip-sync, driven by MedSim, all on-device.)
- **Production tablet release** = + Phase 2.2 (cloud tiers/failover), Phase 5 (hardening, Capacitor, CI).

**Biggest single unblock:** the **blendshape-delta rig** (Phase 1.2) — it's what turns
the avatar from "right shape" into "actually emotes/speaks," and it unblocks
`avatar_exporter` morph baking. Everything else is engine-swaps with seams already in place.
