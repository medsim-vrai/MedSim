# VRAI Faces — Development Review & Next-Steps Plan (2026‑05‑31)

A checkpoint after a long device-bring-up session. Honest review of where we are,
then a sequenced plan. Companion to ROADMAP.md (phases) and ADRs 0028–0030.

---

## 1. Where we are (honest review)

The goal this session was to get the avatar running on a **real tablet** for live
testing. That surfaced a deep chain of **infrastructure** blockers, all now fixed
and documented — and a real product loop that mostly works, with two known gaps.

**Landed + working (committed):**
- **Tablet ↔ portal connectivity** — the long tail of failures was *not* app bugs:
  - CA **trust**, not the cert, was the "not secure" cause → `trust-ca-mac.sh` + `cert-doctor.sh` + re-mint guard (**ADR‑0029**).
  - The tablet "couldn't reach the portal" was a **range-extender/isolated LAN** → fixed by a **flat network** (ping-confirmed).
  - **Single-origin serving** (`VRAI_FACES_SERVE=portal`, **ADR‑0028**) — app + API + WS on `:8765`, one cert.
  - **`MEDSIM_PUBLIC_HOST`** (**ADR‑0030**) — address the portal by a stable name; cert covers both dev-location IPs + the name.
- **On the tablet, confirmed working:** trusted HTTPS (lock), the **skinned avatar** renders (WebGL2), binding + speech WebSocket connect, **cross-origin isolation** (`COI=true`).
- **Voice → AI loop works** via the **cloud-STT toggle** (browser Web Speech, non‑PHI): hold‑to‑talk → transcript → portal AI turn → reply, and the **operator control transcript now shows the exchange** (`/listen` → `log_turn`).
- **Fleet network strategy** documented end-to-end (**ADR‑0030**, `NETWORK-STRATEGY.md` §8) with a researched BOM + MDM payloads.

**Known gaps (open):**
- **G1 — Avatar audio (TTS) doesn't play on the tablet.** The reply frame is pushed; the avatar stays silent. Instrumented with `[speak]` console traces (commit `3e3de3e`) — awaiting the on-device console read to localize (frame arrival / voice‑bound / Kokoro runtime / playback).
- **G2 — On-device STT is blocked on this no-WebGPU tablet.** ONNX‑runtime's wasm backend won't register (tried: local runtime bundle, COI, object-form wasmPaths, hiding `navigator.gpu`). Parked. The cloud stopgap is **non‑PHI**, so on-device is required for real use.
- **G3 — Tech debt:** TEMP pilot code in `main.ts`, `device_stt.ts`, `debug_console.ts`, `speechConsumer.ts` (the 🐞 console + `[speak]`/`[STT]` traces) to gate/remove.

**Reflection:** this was a heavy infra detour, but necessary (no device could connect before) and durable (ADRs + scripts + a fleet strategy). It pulled focus from the *product* (avatar fidelity). The plan below finishes the loop, pays down the debt, then re-anchors on product + ship-readiness.

---

## 2. Guiding priorities
1. **Finish the bedside loop** — make the avatar *speak* (G1). One small fix away from a complete, demoable voice↔avatar loop.
2. **Pay down pilot debt** (G3) so the codebase is clean before building further.
3. **Decide the PHI-safe STT path** (G2) — the cloud stopgap is testing-only; shipping needs on-device or a native recognizer.
4. **Ship-readiness** — execute the ADR‑0030 network/MDM plan for the Option‑2 site, with the Option‑3 transition staged.
5. **Avatar fidelity** — the real product value: speech‑driven lip-sync + expression (Phase 7 / RB‑001), the "biggest single unblock."

---

## 3. Workstream 1 — Complete the bedside loop (immediate, small)

**1.1 Fix avatar audio (G1).** Resume the portal, clean-load the tablet with a session running, do a cloud take, read the `[speak]` lines. Branch on what they show:
- *no `[speak] frame`* → reply frame not arriving → check the WS scenario-id routing in `push_speech` vs the device's WS path (server-side).
- *`no voice bound`* → assign/seed a default TTS voice on bind (the binding may not carry a voice for device-launched avatars).
- *`TTS module loaded` + error* → Kokoro hit the same ONNX wall → **bundle Kokoro's ORT runtime locally** (it still pulls from a CDN; we only bundled it for whisper) and/or apply the `navigator.gpu` handling.
- *`done — 0 chunks`* → synthesis empty → dtype/model issue in `tts_provider`.
- *`done — N chunks` but silent* → audio context / autoplay → ensure the PTT gesture unlocks `audio_pipeline`.

**1.2 Clean up pilot debt (G3).** Gate the 🐞 console behind `?debug=1` (or remove), strip the `[speak]`/`[STT]` `console.*` traces (keep `diag`), keep `cert-doctor`/`trust-ca-mac` (those are durable). One commit.

*Exit criteria:* a trainee speaks → the avatar replies **in voice** with lip-sync, on the tablet; codebase free of TEMP traces.

---

## 4. Workstream 2 — PHI-safe on-device STT decision (G2)

The cloud stopgap unblocks testing but is **non‑PHI**. Shipping needs on-device. Run a **focused spike** (with real instrumentation, not blind iteration):
- **First, get a real error** via `chrome://inspect` remote debugging (or on a desktop Chrome with no WebGPU) — we never saw the untruncated ORT failure.
- **Options, in rough order of effort:**
  1. **Bundle ORT runtime + a non-`/webgpu` build** for both whisper and Kokoro, pinned to a *stable* onnxruntime-web (transformers pins a `-dev` nightly today). Likely the real fix.
  2. **vosk-browser** (Apache‑2.0, no‑WebGPU CPU, self-contained wasm) — a different engine that may sidestep the ORT wall; lower accuracy.
  3. **Target WebGPU-capable tablets** for the fleet (the webgpu path worked in dev).
  4. **Capacitor-native recognizer** (Android `SpeechRecognizer` on-device / iOS `SFSpeechRecognizer requiresOnDeviceRecognition`) — the documented fallback (RB‑002/ADR‑0026).
- **Decision gate:** pick the engine + a target-hardware policy before the fleet buy.

---

## 5. Workstream 3 — Ship-readiness (ADR‑0030, the fleet)

Execute the documented strategy for the **Option‑2** dev/internal site; stage **Option‑3**:
- **Network:** procure the controller-managed AP/gateway/switch (UniFi-class per §8); stand up the flat SSID (isolation OFF), `10.50.10.0/24`, **`portal.medsim.lan`** via gateway DNS + DHCP reservation. Retire the ad-hoc home-network setup.
- **Identity:** enable `MEDSIM_PUBLIC_HOST=portal.medsim.lan` end-to-end (DNS + cert-for-name already supported); `/etc/hosts` for Mac self-test until DNS lands.
- **MDM:** build the provisioning blueprint — push the **Root CA**, the **Wi‑Fi profile**, and the **web-clip/kiosk** (the §8 per-MDM payloads). This removes every manual step that hurt this session.
- **Cert lifecycle:** auto-renew job (≤398d); **decide step‑ca (internal ACME) vs public‑cert + split‑horizon DNS** for Option‑3 (the latter = zero CA distribution, best for sales).
- **Ops:** extend `cert-doctor` → a **site-doctor** preflight (DNS + reachability + egress); a printed runbook; portal autostart + UPS; a **dedicated wired host** (not the MacBook) for deployment.
- **PHI boundary:** device VLAN → portal only, no internet; portal → Anthropic (BAA) only.

---

## 6. Workstream 4 — Avatar fidelity (the product core; gated)

- **Phase 1 (#32, in_progress):** confirm what remains for "real avatar geometry" — the device shows a skinned mesh; close out or re-scope the task.
- **Phase 7 / RB‑001 — the ARKit‑52 blendshape rig.** Per ROADMAP §3 this is the **"biggest single unblock"**: it turns the avatar from "right shape" into actually emoting + lip-syncing, and unblocks `avatar_exporter` morph baking. Execute the plan-strategy: run **RB‑001** (already drafted) → ADR → drop-in the rig → phoneme→viseme lip-sync → emotion mapping. The drive chain (speech→viseme/emotion/idle → `animation_runtime`) is already wired; the gap is the deformation basis.
- **Name-trigger STT** (deferred, post-PTT): fuzzy/phonetic match over a rolling on-device buffer (ADR‑0026), once on-device STT is settled.

---

## 7. Recommended sequence (what to do next)
1. **Relaunch the portal** (`VRAI_FACES_SERVE=portal MEDSIM_HOST=0.0.0.0 …`) — it's currently stopped.
2. **W1.1 — fix the avatar audio** (get the `[speak]` traces → targeted fix). *Completes the demoable loop.*
3. **W1.2 — clean up the TEMP pilot code.**
4. **Decision point:** STT engine (W2) + Option‑3 cert model (W3) — both gate spend; decide before procurement.
5. **W3 — stand up the real dev network + MDM blueprint** (parallelizable; mostly ops/procurement).
6. **W4 — RB‑001 rig** (the product-value track; largest effort, run via the plan strategy).

## 8. Open decisions (need a call)
- **STT engine** for PHI-safe shipping (bundle-stable-ORT / vosk / WebGPU-hardware / Capacitor-native).
- **Option‑3 cert model** (internal step‑ca vs public-cert + split-horizon DNS).
- **Deployment host** (Mac mini vs NUC) + whether the fleet standardizes on WebGPU-capable tablets.
- **Cloud-STT posture:** keep the non‑PHI toggle as a documented testing affordance, or remove once on-device ships?
