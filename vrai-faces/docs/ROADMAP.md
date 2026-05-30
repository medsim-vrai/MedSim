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

### Phase 0 — Decisions  ·  ✅ RATIFIED 2026-05-29
All gated ADRs + §9 product calls resolved:
- **ADR-0019** (emotion engine) — **ACCEPTED**: transformers.js on-device, hybrid (model + lexicon fallback / clinical-affect override). §7.
- **ADR-0020** (local TTS) — **ACCEPTED**: Kokoro→Piper fallback (WebGPU quality + WASM CPU floor). §7.
- **Cloud TTS** — local-only launch; cloud tiers (+ cloud-emotion) are **v1.1**-flagged → Phase 2.2 / 3.
- **Ghost color** — **per-scenario** (optional `ghostColor` on the character binding), default clinical white → Phase 4.
- **Local voices** — **balanced ~6–8** Kokoro voices (IDs chosen in Phase 2).
- **Portal listing** — **derive from the MedSim scenario/character registry** → Phase 4.
- **Resume durability** — **device-restart durable** (persistent storage + stable origin + SessionState migration) → Phase 5.

### Phase 1 — Real avatar (visual fidelity)  ·  _critical path_
1. **mesh_builder — browser-verify the live MediaPipe path** end-to-end (add the real portrait fixture; confirm `detect()` yields 478 landmarks + a real face mesh in Chrome).
2. **Blendshape-delta rig** — replace the procedural morph basis (`morph_basis.ts`, 4 shapes) with a real ARKit-52 deformation basis on the 468-vertex topology (source/author a rig; bundle as a data asset).
3. **avatar_exporter — morph-target baking** — add the per-primitive `targets[]` block now that real deltas exist; round-trip test the GLB morphs. *(blockedBy #2)*

### Phase 2 — Real speech (voice + lip-sync)  ·  ✅ launch-scope DONE
1. **tts_provider — local engine** ✅ Kokoro (q8) wired + Node-verified; local-first via `kokoro-sw.js` (model+voices bundled, 92 MB). **Piper DROPPED (ADR-0021)** — Kokoro-on-WASM is the CPU floor.
2. **tts_provider — failover state machine** ✅ (ADR-0013): chain-walk, lock-to-local, diag-surfaced. Real **cloud tiers** (Azure/ElevenLabs/Cartesia) stay **v1.1** (BAA + keys) per Phase 0.
3. **audio_pipeline — ADR-0015 viseme gating** ✅ native-vs-derived `setVisemeSource`.
   - _Remaining:_ browser e2e of the live Kokoro speech path (→ Phase 5 hardening).

### Phase 3 — Real emotion  ·  ✅ engine DONE
1. **emotion_driver — hybrid engine** ✅ clinical override (lexicon: pain/drowsy) → transformers.js model → lexicon fallback; JSON-only (ADR-0005); `moodForLabel`/`topLabel` unit-tested.
   - The transformers.js model is **wired** (loads in `warmup()`) but **deferred unbundled** by decision — the deterministic **lexicon is the active path** (covers pain/fear/sad/anger/drowsy/relieved + context). The GoEmotions q8 model (~125 MB) drops in later with no code change (like cloud TTS → v1.1).

### Phase 4 — MedSim integration (close the loop)  ·  _done_
1. ✅ **medsim_adapter — real character schema** — Zod against `medsim_v8/schemas/character.json` (§9); `voice_profile`→voice id; portrait attached at launch. _(f04a070)_
2. ✅ **medsim_adapter — WebSocket transport** — cross-app tablet path (reconnect + `seq` dedup), beyond same-origin BroadcastChannel; injectable `WsLike`. _(29b5d8d, ADR-0007)_
3. ✅ **portal — speak/drive path + launchable list** — `portal/vrai_faces.py`: `GET /api/face/characters`, `GET /api/face/{id}/binding` (portrait attach, ADR-0022), `WS /ws/face/{scen}/{id}` + `POST /api/face/{id}/speak` (text+emotion only, ADR-0023).
4. ✅ **shell seam** — `main.ts` reads `?api=` → `portalBinding.bindFromPortal` (fetch bind doc → `bindFromCharacter` connects the speech WS → `avatar_build` from the real portrait), with demo fallback; `speechConsumer` drives frames (emotion → `setEmotion`; text → lazy Kokoro TTS → `audio_pipeline` + visemes). **Loop closed end-to-end.**

### Phase 5 — Hardening & ship
1. ✅ **e2e** — specs: `face-pipeline` (live MediaPipe asset fetches), `bind-path` (mocked
   portal binding → bound mode), `qr-launch`, `pause-resume`, `soak` (5-min slider sweep,
   reads the `window.__vraiPerf` probe). All compile + collect; they **run on real hardware**
   via the nightly `e2e.yml` lane (headless has no WebGPU → WebGL2 fallback).
2. ✅ **perf** — `latency_meter` §5 budgets unit-tested; `perf/probe.ts` exposes fps/heap/
   budget-warns to the soak harness (DEV/?diag gated). Live budget validation = nightly soak.
3. ⏸ **OffscreenCanvas worker** — deferred (optional, perf only; main-thread renderer ships).
4. ◐ **Capacitor** — config + ADR-0006 `apply-ios-permissions.sh` (idempotent PlistBuddy,
   wired into `pnpm sync`). _Native `cap add ios/android` + `.ipa`/`.apk` builds run on a Mac/SDK
   (not in CI/sandbox)._
5. ✅ **CI** — `.github/workflows/ci.yml` (web + portal gate) + `e2e.yml` (nightly browser lane).

**Sandbox-buildable scope complete + verified.** Hardware-gated ops remaining: native
`.ipa`/`.apk` builds, and the live nightly e2e/soak *run* (real browser + ~100 MB assets).

### Phase 5.5 — Character device surface + tablet bring-up  ·  ✅ 2026-05-30
Per-character **device QR** on both tracks (single-encounter ops view + multi-patient
console); multi-patient **avatar assignment** (room-mode opt-in + skin picker) + an
on-the-fly **skin picker in the ops device cells**; a gated **cloud-STT push-to-talk
demo** (ADR-0025) with a portal `/api/face/<id>/listen` reply loop; and the tablet
**HTTPS** path (`scripts/make-dev-cert.sh`, vite + uvicorn TLS, scheme-aware QR/`api`/`wss`)
that gives the device a secure context (WebGPU skin + mic). Full detail in
`BUILD_STATE.md` (2026-05-30). Surfaced the two forward workstreams below.

### Phase 6 — Re-secure the device voice  ·  _gated on RB-002_
Replace the **cloud-STT stopgap (ADR-0025)** with **on-device** name wake-word + trainee
STT (no mic audio leaves the tablet; re-assert ADR-0001/0014), and formalize the
HTTPS/secure-context + device-trust posture. The `device_voice.ts` UI + the `/listen`
reply loop are the seams; swap the engine behind them. Run **RB-002** → ADR → build
`name_trigger` + `device_stt` → retire the stopgap. See
`docs/PLAN-2026-05-30-resecure-and-animation.md §2`.

### Phase 7 — Speech-driven facial animation  ·  _ungated start; full fidelity gated on RB-001_
Make the skinned face visibly **lip-sync + emote** from the character AI's spoken lines.
The drive is already wired (speechConsumer → emotion/viseme/idle → `animation_runtime` →
`morphTargetInfluences`); the gap is the **deformation basis** (the head-proxy has zero
morphs; the real path has only 4 procedural shapes). **B0 (ungated):** light up the real
MediaPipe path on-device + animate the fallback → visible coarse motion now. **B2+ (gated):**
run **RB-001** → ADR → full **ARKit-52 rig** → phoneme→viseme lip-sync → exporter baking →
emotion mapping. The ROADMAP's "biggest single unblock." See `PLAN …§3`.

---

## 3. Critical path vs. full ship

- **Believable local-first demo** = Phase 0 → 1 → 2.1 (local voice) → 3 → 4.
  (Real per-identity face that emotes + speaks with lip-sync, driven by MedSim, all on-device.)
- **Production tablet release** = + Phase 2.2 (cloud tiers/failover), Phase 5 (hardening, Capacitor, CI).

**Biggest single unblock:** the **blendshape-delta rig** (Phase 1.2) — it's what turns
the avatar from "right shape" into "actually emotes/speaks," and it unblocks
`avatar_exporter` morph baking. Everything else is engine-swaps with seams already in place.

---

## 4. Research-driven enhancements (gated work)

Some enhancements would raise performance/fidelity but depend on **gated sources or
more complex systems not currently authorized** — paid/licensed assets, heavier
pipelines (e.g. deformation transfer), or external services that conflict with
local-first/PHI. These are NOT dropped and NOT built inline. Instead:

1. **Capture a research brief** in `research/` (`RB-NNN_<slug>.html` → `.pdf`) defining
   the objective, why it's gated, research questions, evaluation criteria, deliverables,
   and how the result re-enters the build — self-contained enough to hand to **Claude
   Cowork** (deep research) cold.
2. **Park it** against the phase it would enhance (the brief names its gate).
3. **When desired**, run the brief in Cowork → ranked options + a go/no-go.
4. **Decide** → record an ADR in `Memory_management.MD §7` → drop-in implementation
   (seams are kept ready so the swap is small).

This keeps the main build moving on authorized, local-first work while preserving a
fast path to each enhancement the moment it's wanted — no rework, no premature
dependency. See `research/README.md` for the index + lifecycle.

**Open briefs**

| Brief | Enhancement | Gates | Status |
|---|---|---|---|
| RB-001 | Real ARKit-52 blendshape rig (vs. the procedural basis) | Phase 1.2 / 7 | Open |
| RB-002 | On-device voice — name wake-word + trainee STT | ADR-0024 / Phase 6 | Open |

As gated items surface in later phases (a cloud emotion model beyond ADR-0019,
premium-voice procurement, photoreal sculpt per ADR-0002, …), add a brief here rather
than expanding scope inline.
