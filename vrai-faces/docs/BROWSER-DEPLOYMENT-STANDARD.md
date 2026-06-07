# Browser & Device Deployment Standard — VRAI Faces / MedSim V8

**Status:** Adopted 2026‑06‑06 (ADR‑0037). Living standard — update as the fleet evolves.

This document defines **which browsers/devices run what**, and **why the character
voice/animation is architected the way it is.** It exists so the choices stay clear and
defined for future development — and so nobody re‑litigates the iOS findings below.

---

## 1. The iOS reality (the constraint that drives everything)

**On iOS, every browser is WebKit.** Apple requires Safari, Chrome, Edge, Firefox — all of
them — to use the system WebKit engine. "Chrome on the iPad" is a WebKit browser with
Google's UI, so it inherits **all** of Safari's limits. *Switching browsers on the iPad
changes nothing.* (The EU‑DMA alternative‑engine allowance is not something we can depend
on for deployment.)

The two WebKit limits that block on‑device character voice, both reproduced on the iPad
(2026‑06‑06, debug console):

| Limit | Symptom | Consequence |
|---|---|---|
| **WebGPU memory ceiling** | `[webgpu] RangeError: Out of memory` when the TTS model tries to init | The avatar renderer + on‑device whisper STT already consume the tablet GPU; a **third** WebGPU model (on‑device TTS) does not fit |
| **`speechSynthesis` gesture lock** | `speak()` called ~5 s after PTT release → no `onstart`, no `onerror`, just silence | iOS refuses async (non‑gesture) speech; the browser‑voice fallback can't carry the reply |

Net: **the iPad cannot synthesize the character's voice locally.** The Web Audio
`AudioContext` *can* be unlocked (once, on a user gesture — ADR‑0008) and plays async audio
fine; it just needs an audio **source** that isn't the (dead) on‑device TTS.

---

## 2. Device classes & browser standard

### A. Character devices — the bedside avatar tablets
- **Targets:** iPad (WebKit) **and** Android tablets (Chromium, e.g. Galaxy Tab S9).
- **Rule: design to the WebKit floor.** If it works on the iPad it works on Chromium; the
  reverse is false. Never rely on Chromium‑only behavior on the character path.
- **Stack:**
  - **Render:** WebGPU avatar (works on iPad).
  - **STT (trainee voice):** on‑device whisper, WebGPU — PHI‑safe, validated on iPad.
  - **TTS (character voice):** **server‑side** (see §3). *Never* on‑device on this path.
  - **Audio out:** the gesture‑unlocked Web Audio `AudioContext` (works on iPad).

### B. Operator / management / non‑character devices
- Control room, scenario authoring, content/export **downloads**, dashboards.
- **Standardize on Chrome / Chromium** (desktop Chrome, Chromebook, Android Chrome).
- No WebKit constraints → full features (File System Access, large downloads, heavier
  compute). The portal/control‑room UI assumes Chromium.

> One sentence to remember: **character tablets are built to the WebKit floor; everything
> else requires Chrome.**

---

## 3. Character voice + animation architecture (the resolution)

**Move TTS off the device and onto the portal.** The character's reply is the AI's
words — **not** trainee input, so it is **not PHI** — therefore synthesizing it server‑side
is allowed under local‑first/PHI rules (ADR‑0001/0014). Flow:

```
trainee speaks ─(on-device whisper, PHI-safe)─▶ text
   └▶ POST /api/face/{id}/listen ─▶ character AI reply (text)
        └▶ portal TTS ─▶ audio bytes ──(speech frame: text + audioB64 + emotion, over WS)──▶ iPad
             └▶ Web Audio AudioContext (already gesture-unlocked) ─▶ SOUND
                  └▶ energy-envelope visemes ─▶ jawOpen ─▶ LIP-SYNC
                  └▶ frame.emotion ─▶ setEmotion ─▶ EXPRESSION
```

This **bypasses both WebKit blockers**: no on‑device TTS (no WebGPU OOM) and no
`speechSynthesis` (no gesture lock). The `f.audio` → `enqueueAudio` path and the
envelope‑viseme bridge already exist client‑side (`speechConsumer`, `audio_pipeline`); the
work is on the **portal** (always synthesize) plus a default flip on the client.

### TTS engine — RESOLVED 2026‑06‑06 → ElevenLabs (validated on iPad)
- **Chosen: ElevenLabs (cloud).** Realistic voices, already wired. Standalone (no operator),
  the portal auto‑selects a character‑appropriate voice via `voices.candidates_for(character_id)`
  (e.g. Mr. Hayes/P‑014 → *"Bill — Wise, Mature, Balanced"*, male/old); the operator can override
  in the control room. Key from the session, else env / `~/.medsim/elevenlabs.key`.
- **Trade‑off (accepted):** ElevenLabs is CLOUD — the **non‑PHI reply text** leaves the portal per
  reply (network + per‑use cost), acceptable per ADR‑0031. The trainee's own audio NEVER leaves the
  device (on‑device STT). Each reply ≈ one short API call.
- **Future option (not chosen now):** self‑hosted local TTS (Kokoro/HeadTTS/Piper) for a fully
  offline, $0/use voice if the cloud dependency becomes undesirable. The server‑audio plumbing is
  engine‑agnostic, so swapping it later is a portal‑only change.

### Client on‑device TTS (Kokoro)
- **Disabled on the character path by default.** Crashes/OOMs on iPad WebKit (latched off
  via `kokoroBroken` after one failure). May be retained as an **optional** path for capable
  Chromium devices only — but server‑audio stays the default for reliability + consistency.

---

## 4. Caching & startup strategy (easy startup)

Startup cost on a character device is dominated by model downloads. The §3 decision is
**also the biggest startup win**, because it deletes the largest model from the device.

- **Service Worker** (`app-sw.js`) precaches the app shell + ORT runtime on install.
- **Persist models after first download** (Cache API / IndexedDB): the whisper STT model and
  the MediaPipe landmarker — so 2nd+ launches don't re‑fetch.
- **Server‑audio removes the on‑device TTS model entirely** (~the largest asset) → less to
  download, less storage, **less WebGPU memory (this is what was OOM‑ing), faster cold start.**
- **WebGPU memory budget (character device):** renderer + whisper STT **only**. Do not add a
  third WebGPU consumer on this path — that is exactly what broke.
- **Optional — pre‑warm at pairing:** when a device is first bound, precache the models so the
  first real scenario launch is instant.
- Cross‑refs: `docs/OPTIMIZATION-REGISTER.md` → OPT‑004 (bundle‑split), OPT‑005 (per‑capability
  model shipping — don't precache a variant the device won't use).

---

## 5. What NOT to do (so we don't relearn it)

- ❌ **Don't "switch to Chrome on the iPad"** to dodge WebKit limits — it *is* WebKit.
- ❌ **Don't run on‑device TTS on the character path** — OOMs on iPad, bloats startup everywhere.
- ❌ **Don't rely on `speechSynthesis`** for the character voice on iOS — gesture‑locked for
  async replies; keep it only as a last‑ditch fallback on Chromium.
- ❌ **Don't add a third concurrent WebGPU model** to a character tablet.
- ❌ **Don't strip the debug / diagnostics tooling in a "production cleanup."** It is gated
  OFF by default (real sessions stay clean) and enabled **on demand**, so it costs nothing
  to keep and stays available for field troubleshooting / a future bug tracker:
  - `?diag=1` → the **diagnostics panel** only (fps · per‑module state · timeline; starts minimized).
  - the **🐞 launch‑page QR toggle** (`?debug`) → the diagnostics panel **plus** the on‑device
    console + morph/STT probes, in one scan. `localStorage['vrai:debug']='1'` makes it sticky.
  Keep the option open to surface / expand this (e.g. wire it to the control‑room bug tracker) later.

---

## 6. Open decisions (resolve before/with implementation)

- [x] **Portal TTS engine:** RESOLVED 2026‑06‑06 → **ElevenLabs** (cloud), with standalone
  auto‑voice via `candidates_for`. Validated on iPad. Self‑hosted local stays a future option.
- [ ] **Keep the optional client Kokoro path** for Chromium character devices, or remove it
  entirely for one code path everywhere?
- [ ] **Audio transport size:** inline base64 in the WS frame (simple) vs a short‑lived
  fetch URL for the audio (lighter frames) — pick once we measure reply sizes.
