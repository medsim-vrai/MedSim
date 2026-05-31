# On-device pilot — STT + speech-driven animation (Phase 6/7)

The ship-gate from **ADR-0026**: every latency/WER/thermal number in the research
was laptop-measured, so the on-device STT + animation must be validated on the
real device before we tune + bundle. Primary target: **Android Chrome tablets**;
iOS Safari 26 secondary. The control portal runs on the MacBook.

The app is instrumented for this: with push-to-talk enabled, the panel shows a
**`STT: <backend> · cold <ms> · last <ms>`** line — read those numbers straight
off the device. Add **`&diag=1`** to the URL for the diagnostics overlay (fps,
backend logs, errors).

## Setup (once)
1. Portal in LAN + HTTPS mode on the MacBook: `MEDSIM_HOST=0.0.0.0 python3 run_portal.py`
   (TLS auto-on once the dev cert exists). For the *cached/production* build, add
   `VRAI_FACES_SERVE=preview`.
2. Trust `portal/data/certs/rootCA.pem` on each tablet (one-time).
3. Assign each test character a **real face photo** skin (Personas page or the ops
   device cell) — needed to exercise the real MediaPipe mesh, not just the egg.
4. On the tablet: scan the character's device QR (or Add-to-Home-Screen for the icon),
   on the same Wi-Fi. Grant the mic prompt the first time.

## Part A — STT (push-to-talk)
For each take: tap **🎙 Enable push-to-talk** → **hold**, speak a clinical phrase,
**release**. Read the metrics line + judge the transcript shown in the status.

| # | Phrase spoken | Transcript shown | Backend | Cold-load (1st only) | Last (ms) | Words wrong | Notes |
|---|---|---|---|---|---|---|---|
| 1 | e.g. "blood pressure 120 over 80" | | webgpu/wasm | | | | first take = cold |
| 2 | e.g. "administer 4 milligrams ondansetron" | | | — | | | |
| 3 | … | | | — | | | |

**Targets (ADR-0026):** backend ideally **webgpu** on Android; **release→text < 1.5 s**
(the `last` number); **WER < 12%** on clinical phrases; **model ≤ ~80 MB, cold-load ≤ ~5 s**.
Note any **q8 gibberish** (garbled output → a dtype tune, not a blocker).

## Part B — speech-driven animation (B1)
With a scenario running on the MacBook (so it's a real AI reply, not an echo):
- [ ] After a take, the avatar **speaks** the reply (Kokoro TTS; first reply lazy-loads the voice).
- [ ] The **mouth/jaw moves in sync** with the spoken audio (energy → jawOpen).
- [ ] The **expression shifts with emotion** (e.g. a worried/relieved line reads on the face).
- [ ] With a **real-face skin**, the avatar is a sculpted face mesh; with none, it's the
      animated head-proxy "egg". (Add `&diag=1` → mesh_builder logs "real mesh" vs "fallback".)
- [ ] Lip-sync feels tied to the audio within the §5 budget (no obvious lag).

## Part C — sustained session (thermal / stability)
Run ~**20 minutes** of normal PTT use:
- [ ] No thermal throttle / the device doesn't get hot or visibly slow.
- [ ] `&diag=1` fps stays smooth; no memory-leak crash (whisper WebGPU has known leak bugs).
- [ ] `last` latency doesn't creep up over the session.

## Report back
Fill the table + check boxes (rough numbers are fine). The decisions they drive:
- **dtype tune** if transcripts are garbled (q8 WebGPU bug) or WER is high.
- **bundle whisper-tiny** via `setup:assets` (offline + skip the cold-load) once the
  backend/size look right.
- **WASM-only fallback** posture if WebGPU is flaky on the target tablets.
- whether to pursue the **Capacitor-native iOS** path (only if iOS Safari underperforms).
