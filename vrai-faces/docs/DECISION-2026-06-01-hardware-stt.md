# Decision memo — Fleet hardware + PHI-safe STT (W2/W3)

**Date:** 2026-06-01 · **Status:** **RATIFIED 2026-06-01 → ADR-0032** (final platform pending the head-to-head pilot)
**Decides:** Open questions in `PLAN-2026-05-31-next-steps.md` §8 (STT engine; fleet
WebGPU-hardware policy; Option-3 cert model) and unparks task #50.

---

## 1. The question

The bedside loop works on the current tablet only via two **cloud stopgaps**: browser
cloud STT in (non-PHI — trainee audio leaves the device) and portal ElevenLabs out
(PHI-fine — the character's words). The **single remaining PHI blocker is STT**.
Shipping PHI-safe means the trainee's microphone audio must be transcribed
**on-device** (ADR-0001 local-first; ADR-0014 PHI). So: *which STT engine, and on
what hardware?*

## 2. What is already settled (RB-002 → ADR-0026)

The on-device-voice deep research (2026-05-30; 29 sources, 25 claims verified) already
chose the engine:

- **PTT STT = `whisper-tiny.en` (ONNX) via transformers.js, WebGPU with WASM fallback.**
  MIT-licensed, ~80 MB, and transformers.js is **already a dependency** (Kokoro TTS +
  emotion) — this adds a *model*, not a library.
- Chrome on-device Web Speech → **NO-GO** (desktop-only; absent/cloud on iOS).
- Name wake-word → **deferred** (no clean open KWS engine); use fuzzy match over a
  rolling STT buffer later. PTT ships first.
- **Every latency/WER/thermal number was laptop-measured** → ship-gated on a real-device
  pilot (`PILOT-2026-05-30-on-device.md`).

**This memo does not relitigate the engine. It resolves the hardware question the engine
depends on** — which this session's bring-up turned from theoretical into decisive.

## 3. The new evidence (this session)

RB-002 assumed a **WASM CPU fallback** would cover devices lacking WebGPU. On the actual
test tablet (a no-WebGPU Samsung unit) that assumption **failed**: the ONNX-runtime WASM
backend would not even register — for *both* whisper (STT) and Kokoro (TTS) — so the
device can run **no** on-device ONNX model. The WASM floor is not dependable on
arbitrary hardware.

**Implication:** the reliable on-device path is **WebGPU, not WASM-fallback**. Therefore
the fleet must be **WebGPU-capable hardware**, chosen deliberately — not whatever tablet
is cheapest. The upside: a WebGPU device runs the *entire* on-device stack — whisper STT
**and** Kokoro TTS **and** real lip-sync — so this one decision closes the PHI gap and
makes the portal-ElevenLabs path an *optimization*, not a crutch.

## 4. Hardware landscape (researched 2026-06-01)

| Platform | WebGPU availability | Fragmentation risk | MDM | Notes |
|---|---|---|---|---|
| **iPad (A12+)** | **Guaranteed** on **iPadOS 26 / Safari 26** (all models 2018–2020+) | **None** — uniform Apple GPU | **Best-in-class** (Apple Business Manager + Configurator/Jamf) | RB-002 named Safari 26 WebGPU the iPad unblock |
| **Android — Snapdragon/Adreno** | **Yes**, Chrome 121+ / Android 12+ | Low (Adreno is first-class) | Good (Android Enterprise / Knox) | e.g. Galaxy Tab S9/S10 (Snapdragon), OnePlus Pad (SD 8) |
| **Android — ARM/Mali** | **Yes**, Chrome 121+ / Android 12+ | Medium (driver-dependent) | Good | e.g. Galaxy Tab S9 FE (Exynos 1380 / Mali) — verify per unit |
| **Android — Samsung Xclipse (Exynos)** | **WIP — not yet supported** | **High — disqualify** | — | Exynos 2200/2400, Tab S10 FE (Exynos 1580 / Xclipse) |
| **Android — pre-Vulkan / Android < 12** | **No** | n/a — disqualify | — | ~23% of Android devices lack Vulkan 1.1 |

**Reading:** Android WebGPU is real but a **per-GPU lottery** — Adreno/Mali yes, **Samsung
Xclipse/Exynos WIP**, pre-Vulkan no. The failed unit fits the disqualified column. iPad
removes the lottery entirely.

## 5. Decision (proposed)

1. **STT engine: `whisper-tiny.en` via transformers.js on WebGPU.** (Confirms ADR-0026.)
   Bundle the model locally via `setup:assets` (offline + no cold-load) after validation.
2. **Standardize the fleet on WebGPU-capable hardware, iPad-first.**
   - **Primary: iPad (A12+ / iPadOS 26+).** Uniform guaranteed WebGPU, no driver lottery,
     strongest MDM. Recommended baseline: **iPad 11th-gen (A16)** (~$349–449) for cost, or
     **iPad Air (M-series)** (~$599) for headroom. This is the lowest-risk fleet.
   - **Cost alternative: vetted Snapdragon/Adreno Android only** (e.g. Galaxy Tab S9/S10
     *Snapdragon*, OnePlus Pad). **Hard rule: NO Samsung Exynos/Xclipse, NO "FE" unless the
     specific GPU is verified, NO Android < 12 / non-Vulkan.** Every model WebGPU-tested
     before purchase.
3. **On-device Kokoro TTS + lip-sync come along for free** on this hardware. Keep the
   portal-ElevenLabs voice (ADR-0031) as the device-agnostic fallback + premium-voice
   option, not a requirement.
4. **Retire the non-PHI cloud STT** as the default once on-device is validated; keep it
   only as a clearly-labelled non-PHI testing toggle (or remove — see §8).

## 6. Validation gate (MUST pass before any fleet buy)

Buy **1–2 candidate units** (recommend: one **iPad 11th-gen** + optionally one
**Snapdragon Android** for comparison) and run the existing **`PILOT-2026-05-30-on-device.md`**
protocol. Pass criteria (ADR-0026):

- Backend resolves to **webgpu**; PTT **release→text < 1.5 s**.
- **Clinical WER < 12%** on drug/vitals phrases (the unmeasured risk — jargon inflates WER).
- Model **≤ ~80 MB, cold-load ≤ ~5 s**; **no thermal throttle over 20 min**.
- No q8/WebGPU gibberish (else a dtype tune).

Only on a pass do we bulk-buy + bundle the model. A fail routes to the §7 fallbacks.

## 7. Fallbacks (only if in-browser WebGPU underperforms on the chosen device)

- **vosk-browser** (Kaldi/WASM, Apache-2.0) — CPU floor, no WebGPU needed; **audit the
  `.wasm` GPL build-provenance (issue #12) before shipping**. Lower accuracy.
- **Capacitor-native** — iOS `SFSpeechRecognizer(requiresOnDeviceRecognition)` is the one
  robust on-device recognizer Apple ships; Android on-device `SpeechRecognizer`. Adds a
  native bridge; keep documented, build only if needed.
- **NOT recommended: BAA-covered cloud STT.** It would satisfy ADR-0014 (PHI via BAA) but
  violates ADR-0001 (local-first / no PHI off-device). Only revisit if on-device proves
  unviable on all reasonable hardware — a separate ADR.

## 8. Cert model (Option-3, W3 sub-decision)

Per ADR-0030: **Option-2 (internal pilot)** = our CA + `MEDSIM_PUBLIC_HOST=portal.medsim.lan`,
trust pushed by MDM (already supported). **Option-3 (multi-site/sales)** → recommend
**public certificate + split-horizon DNS** (zero CA distribution — the cleanest sales
story) over internal `step-ca` ACME; decide at the Option-3 boundary, not now.

## 9. Rough BOM (Option-2, ~20 devices)

| Item | Est. |
|---|---|
| 20 × iPad 11th-gen (A16) | ~$7,000–9,000 |
| MDM | Apple Business Manager (free) + Apple Configurator, or Jamf (~$3–8/device/mo) |
| Network (ADR-0030) | UniFi-class AP/gateway/switch — see `NETWORK-STRATEGY.md` §8 |
| Validation units (now) | 1 iPad (+ optional 1 Snapdragon Android) — **the only spend to approve today** |

## 10. Ratified (2026-06-01)

- [x] **Platform: validate BOTH head-to-head**, then standardize on the winner.
- [x] **Validation buy approved** (2 units — see §11). The only spend now.
- [ ] Cloud-STT toggle keep-vs-remove → decide *after* the pilot (default: keep as a
      labelled non-PHI testing affordance until on-device is proven, then remove).
- [ ] Option-3 cert model → decide at the Option-3 boundary (lean public-cert + split-horizon DNS).

→ Recorded as **ADR-0032**; task #50 unparked against the purchased units. The final
platform pick is ratified after §11's pilot.

## 11. Validation buy + head-to-head pilot plan

**Buy these two (user action — I don't purchase):**

| Unit | Why this one | GPU / WebGPU | RAM | Approx |
|---|---|---|---|---|
| **iPad 11th-gen (A16, 2025)** | Cheapest WebGPU-*guaranteed* iPad (iPadOS 26 / Safari 26). If the *floor* passes, the whole iPad fleet is cheap. | Apple GPU — uniform, guaranteed | 6 GB | ~$349–449 |
| **Samsung Galaxy Tab S9 (Snapdragon 8 Gen 2)** | The enterprise Snapdragon/Adreno pick (Knox MDM). Adreno is first-class for Chrome WebGPU; **no Exynos variant exists for the S9**, so it sidesteps the Xclipse problem. | Adreno 740 — first-class | 8/12 GB | ~$600–800 |

*If the A16 iPad struggles on RAM/thermal, the fleet steps up to an iPad Air (M-series, 8 GB) — but test the floor first.*

**Run on each:** the existing `PILOT-2026-05-30-on-device.md` protocol (Parts A/B/C),
launched from the portal in durable device mode, CA trusted (Mac + each tablet), real-face
skin assigned, a scenario running for true AI replies. Capture per device:

| Metric (ADR-0026 target) | iPad 11th-gen | Galaxy Tab S9 |
|---|---|---|
| Backend resolved (want **webgpu**) | | |
| PTT release→text (**< 1.5 s**) | | |
| Clinical WER (**< 12%**, drug/vitals phrases) | | |
| Cold-load (**≤ 5 s**) / model ≤ 80 MB | | |
| 20-min thermal (**no throttle**) | | |
| q8/WebGPU gibberish? (dtype tune if so) | | |
| Lip-sync tracks audio? (B1) | | |

**Decision rule:** the device that meets all targets wins; ties → iPad (uniformity + MDM).
A double-fail routes to §7 fallbacks. On a pass: bundle whisper-tiny via `setup:assets`,
fleet-buy the winner, demote cloud STT.

*App is already instrumented for this:* the STT metrics line + `&diag=1` overlay are fed
by `diag.push()` (NOT gated by the new `?debug` flag), so the pilot numbers read straight
off the device.

## Sources
- Chrome 121 — WebGPU on Android (Android 12+, Qualcomm/ARM): https://developer.chrome.com/blog/new-in-webgpu-121
- WebGPU on Android (Khronos/Google, GPU support detail): https://www.khronos.org/developers/linkto/webgpu-on-android
- Chrome WebGPU implementation status (Xclipse WIP; Imagination Android 16+): https://github.com/gpuweb/gpuweb/wiki/Implementation-Status
- WebGPU troubleshooting / blocklist: https://developer.chrome.com/docs/web-platform/webgpu/troubleshooting-tips
- iPadOS 26 compatible models (A12+): https://support.apple.com/guide/ipad/ipad-models-compatible-with-ipados-26-ipad213a25b2/ipados
- WebGPU in Safari 26 (iOS/iPadOS): https://webkit.org/blog/16993/
- RB-002 findings (this repo): `research/RB-002_findings.md` → ADR-0026
