# RB-002 — Findings (executed 2026-05-30, deep research)

Adversarially-verified deep research (6 angles → 29 sources → 132 claims → 25
verified, **19 confirmed / 6 killed**). Decision recorded as **ADR-0026**.
This is the durable record (the raw run output lives only in a temp dir).

## Verdict: CONDITIONAL GO — split by capability + platform

### PTT speech-to-text (the trainee→character path) — **GO, on-device**
1. **transformers.js + `whisper-tiny.en` (ONNX) on WebGPU, WASM fallback** — *recommended.*
   Officially demonstrated on-device path (HF Transformers.js v3); `whisper-tiny.en`
   is **MIT** and fits the ~80 MB budget. **`transformers.js` is already a project
   dependency** (Kokoro TTS + emotion), so this adds a *model*, not a new library.
   - Enabler: **WebGPU now ships by default in Safari 26 (iOS/iPadOS, fall 2025)** —
     removes the historical iPad blocker (high confidence; WebKit blog + W3C WG). ✓ 3-0
   - Risks: quantized/q8 WebGPU decoders can emit gibberish (transformers.js #1317);
     `whisper-base` (~200 MB) **exceeds** budget → use **tiny** only.
2. **Moonshine v2 Tiny** — emerging, very low latency (constant lookahead; ~5.8× faster
   than Whisper Tiny on M3), but **no turnkey in-browser/JS path** (official repo is
   Python/native only), WER ~12.01% (general-domain, at the threshold), latency measured
   on laptop only. *Promising; not turnkey — revisit later.*
3. **`vosk-browser` (Kaldi/WASM)** — **Apache-2.0**, no WebGPU needed → the **CPU floor**
   where WebGPU is absent/unreliable. Caveat: a transitive GPL/GSL build-provenance
   question (issue #12) → audit the actual `.wasm` before shipping.

### Name wake-word — **DEFER (no clean engine)**
- **No fully-open in-browser keyword-spotter** survived verification with arbitrary
  per-scenario name support.
- **Picovoice Porcupine** is the only verified custom-name browser KWS, but: commercial
  **AccessKey call-home** (license validation), free tier only ≤3 users/mo, and
  localStorage-derived machine IDs that break on cache clears → **rejected** for a
  privacy-first bedside PWA.
- **Recommended strategy:** fuzzy/phonetic match over a **rolling on-device STT buffer**
  (no dedicated wake model). *Medium confidence — the false-accept (<1/10 min) and
  detect-latency (<500 ms) targets were NOT measured; highest-uncertainty area.*

### Chrome on-device Web Speech (Option C) — **NO-GO**
Experimental, Chromium-desktop-only, **not** Android initially, **absent on iOS Safari**
(routes to Apple's cloud). Cannot meet the on-device constraint on either target. ✓ 3-0

### Capacitor-native (Option E) — **documented fallback, unassessed**
No surviving claim evaluated it, but iOS `SFSpeechRecognizer(requiresOnDeviceRecognition)`
is the one robust on-device recognizer Apple ships → keep as the **iOS fallback** if
in-browser Whisper underperforms.

## The decisive open risk (validation gate)
**Every quantitative number (latency, WER, footprint) was measured on laptop/desktop
CPU — none on an iPad-class tablet or in a mobile browser.** Clinical-domain WER is also
unmeasured (jargon/drug names inflate WER). → **Ship-gated on an on-device pilot**:
measure PTT latency, clinical WER, and 20-min thermal on real iPad Safari 26 before
retiring the cloud stopgap.

## iOS-Safari constraints to honor
- WebGPU available by default in Safari 26 (good); **secure context (HTTPS) required** for
  the mic (we have it via the dev cert).
- iOS PWAs throttle/suspend background audio → an **always-on** rolling-STT wake word is
  power/thermal-sensitive and may be suspended when backgrounded; PTT (foreground, explicit)
  is unaffected — another reason PTT ships first.

## Key sources (primary)
- WebKit — Safari 26 WebGPU: https://webkit.org/blog/16993/
- Transformers.js v3 (WebGPU ASR): https://huggingface.co/blog/transformersjs-v3
- Real-time Whisper WebGPU demo: https://huggingface.co/spaces/Xenova/realtime-whisper-webgpu
- Moonshine v2 (arXiv 2602.12241): https://arxiv.org/html/2602.12241v1
- vosk-browser: https://github.com/ccoreilly/vosk-browser
- Porcupine Web: https://picovoice.ai/docs/quick-start/porcupine-web/
- Web Speech processLocally (MDN): https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/processLocally
- Capacitor speech-recognition: https://github.com/capacitor-community/speech-recognition

→ Decision + consequences: **ADR-0026** (`Memory_management.MD §7`).
→ Build path: `docs/PLAN-2026-05-30-resecure-and-animation.md §2` (A2–A6).
