# ADR-0038 — Room-local STT: the portal Mac transcribes for audio-only stations

**Status:** Accepted (instructor-ratified 2026-06-11) · **Relates:** ADR-0001 (local-first),
ADR-0014 (PHI guardrail), ADR-0025 (cloud Web Speech stopgap), ADR-0026 (on-device STT),
ADR-0027 (device token), FR-006 (audio-only lite station), OPT-002 (Moonshine, now Plan B)

## Context

FR-006 field numbers on the target low-cost Android tablet (2026-06-11, after the full
three-layer ORT fix chain made the pipeline functional): whisper-tiny.en q8 on the CPU wasm
backend transcribed a **4.8 s clip in 17.0 s** (~3.5× slower than real time) and **misheard
the utterance** ("descend" for "send"). Even a perfect 4× multi-thread speedup lands ~4–5 s
— far over the ≤1.5 s release→text target (RB-002) — and tiny-grade accuracy stands. The
rest of the loop is healthy on the same tablet (character reply 2.3 s, server voice fine).
On-device inference on this hardware class is not viable; the question became *where* the
transcription work moves. The instructor was offered three routes (cloud-primary, Moonshine
on-device, portal-Mac) and ratified the portal-Mac route.

## Decision

1. **Trainee microphone audio may cross the room's LAN to the instructor's portal over TLS —
   and to no other destination.** The PHI boundary relaxes from *device-local* to
   **room-local**: the portal Mac already holds the scenario, the EHR seed, and every turn's
   transcript text, so audio-to-the-portal introduces **no new trust party**. Audio is
   transcribed in memory and discarded — never written to disk, never logged, never
   forwarded. Cloud STT (audio to Google/any third party) remains **prohibited** for
   teaching use; the ☁︎ toggle stays a labeled testing-only stopgap (ADR-0025 unchanged).
2. **Default routing by device capability:** devices **without WebGPU** (the low-cost
   audio-station class) default to the portal route; devices **with WebGPU** (iPad class)
   keep the validated fully-on-device path — strictest privacy where the hardware can
   afford it. URL knob `&stt=portal|webgpu|wasm` pins a route for diagnosis.
3. **On-device wasm is the automatic backup** (instructor requirement): after a portal-route
   failure the station names the failure, lazy-loads the local model in the background, and
   uses it for subsequent takes — degraded (slow) but functional if the portal drops
   mid-session.
4. **Engine:** `faster-whisper` (CTranslate2, MIT) running **whisper-small.en int8** on the
   portal Mac — a *bigger, more accurate* model than the tablets could ever run, at
   sub-second latency for PTT-length clips. Model auto-downloads once from Hugging Face to
   the Mac's cache (~250 MB; instructor-approved 2026-06-11); offline kits pre-warm it.
   `MEDSIM_STT_MODEL` overrides the size (`tiny.en`/`base.en`/`small.en`);
   `MEDSIM_STT_WARM=0` skips the boot-time warm load.
5. **Endpoint:** `POST /api/face/stt` — raw 16 kHz mono float32 PCM body (the exact buffer
   the device already produces), ≤30 s cap, optional ADR-0027 device-token enforcement
   (same posture as `/listen`). Response `{ok, text, ms, model}`.

## Consequences

- New portal dependency: `faster-whisper` (+ CTranslate2/numpy wheels), MIT-licensed; portal
  RAM +~600 MB while the model is resident; portal start gains a background warm thread.
- The audio-station release→text path becomes: flush → decode → resample (all on-device,
  ~0.2 s) → ~300 KB POST over LAN → Mac inference (~0.3–0.8 s) — comfortably under target,
  with small.en accuracy.
- The kit (FR-004 travel router) needs no internet: the model is cached on the Mac and the
  LAN hop is local.
- Moonshine (OPT-002) is demoted to Plan B — only needed if a deployment requires
  *device*-local STT on no-WebGPU hardware (e.g. stations that must survive portal loss at
  full speed).

## Alternatives rejected

- **Cloud Web Speech as primary** (instructor's opening suggestion): fastest to enable, but
  reverses the system's load-bearing privacy promise (fail-closed PHI posture, ADR-0014) by
  shipping trainee speech to a non-BAA third party as the *default* path. Rejected in favor
  of a route that is both private *and* faster.
- **Moonshine on-device:** right shape for CPU short-clips (no 30 s padding) but unproven on
  the exact target tablet, tiny-grade accuracy, and another ~60 MB bundled asset; kept as
  the documented fallback research line.
- **Bigger threads/quantization tuning of the current path:** arithmetic can't close a
  17 s → 1.5 s gap on this silicon.
