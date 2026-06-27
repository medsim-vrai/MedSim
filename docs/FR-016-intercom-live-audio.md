# FR-016 — Live two-way intercom audio (PTT + page-all)

**Status:** DONE — WebRTC two-way, **field-validated on iPad + Android** (nurse↔bed
+ page-all). **Logged:** 2026-06-25. **Field-validated:** 2026-06-26.

## Problem
The nurses-station intercom was **text-only** (M28): the nurse typed a message →
the bedside spoke it via TTS. There was no live audio, no press-to-talk control
per room, and no way to page every room at once.

## What shipped — "radio + caption" over **WebRTC** (FR-016b)
Press-to-talk streams the **real mic voice over a WebRTC peer connection** (Opus,
nurse⇄bed mesh, host-ICE only → LAN P2P, no STUN/TURN). The mic is captured
**once** and streamed continuously — gated per-peer by `track.enabled` (PTT) so a
nurse can talk to one bed or 📢 all beds. The `/ws/room/{room_code}` WebSocket is
only the **signaling** channel (`rtc_hello`/`offer`/`answer`/`ice`, addressed by
`to`); the audio never traverses it. In parallel, `intercom_state` (calling
indicator) + `intercom_text` (STT caption / typed page) ride the WS as the **text
fallback** — so the message lands even if P2P can't establish. Half-duplex.

> Why WebRTC: the prior MediaRecorder transport hit a **known browser bug**
> (Chromium #343157156 — "MediaRecorder stops recording after working for a
> while"), which is what broke Android after a few presses; raw-PCM before it kept
> swinging pitch slow⇄fast. WebRTC captures the mic once and lets the browser own
> encoding/rate/jitter, eliminating both bug classes. Reference pattern:
> `github.com/codewithmichael/webrtc-intercom`.
>
> Evolution: raw walkie-talkie → STT→TTS → raw PCM/WAV+measured-rate →
> MediaRecorder → **WebRTC** (current).
>
> P2P caveat: WebRTC needs the devices to reach each other on the Wi-Fi; a guest/
> enterprise AP that "isolates" clients would block it. The voice degrades to the
> WS text caption/typed page in that case. A media server (SFU) relay would be the
> fix if an isolated network must carry voice. **Needs on-device validation**
> (WebRTC behaviour is device/network-specific).

- **Nurses station** (`nurse_station.html` / `.js`): a 🎙 **Hold to talk** button
  per bed card, a 📢 **Page all rooms** button in the header, a typed-page
  fallback per bed (existing `/api/intercom/{eid}/page`), and a banner + bed-card
  pip that light up when a room calls back.
- **Bedside** (`station.html`): a 📞 **Call nurses station** button (distinct from
  the patient "Hold to talk"), and a banner when a page comes in (single bed or
  page-all). Hidden when the station isn't part of a room.

## Design
- **Transport** — `ws_room.handle_room_ws` was push-only; it now **relays** a
  whitelist (`intercom_text`, `intercom_state`) back to the room and discards
  everything else. 64 KB/frame guard. The `room_code` is the access token (same
  trust model as the rest of the channel).
- **Routing is client-side** by `from` / `scope` / `encounter_id`
  (`intercom.js`): the nurse reacts to `from:"bed"`; a bed reacts to
  `from:"nurse"` when `scope:"all"` or `encounter_id` matches. So a sender never
  echoes itself and beds never hear each other.
- **Voice** — on press, `MediaRecorder` records the mic (one clip, ≤12 s); on
  release the blob is base64'd into an `intercom_audio` frame (with its `mime`).
  The far end plays it via `AudioContext.decodeAudioData`. The browser writes the
  **true sample rate into the container**, so playback speed/pitch is always
  correct with zero rate math (this replaced a fragile measure-the-rate scheme
  that kept swinging pitch slow⇄fast, and ScriptProcessor capture that flaked on
  Android). iOS autoplay is unlocked by resuming the `AudioContext` on the PTT
  press / any tap; a "🔊 tap to enable" chip covers a pure receiver.
- **Codec** — `pickRecMime()` prefers `audio/mp4` (AAC: iPad Safari + modern
  Chrome both decode it), falling back to `audio/webm;codecs=opus`. `decodeAudioData`
  sniffs the container, so the receiver needs no rate/format hints. An undecodable
  clip (e.g. WebM reaching iOS Safari) is skipped and the caption covers it.
- **Caption** — in parallel, `SpeechRecognition` (if present) sends the
  transcript as an `intercom_text` frame; the far end shows it (no TTS — the real
  voice already plays). Typed box sends the same frame. `intercom_state` pre-rolls
  a "calling…" indicator on press.
- **Relay** — `ws_room` whitelist = `intercom_audio` / `intercom_text` /
  `intercom_state`; 1.2 MB/frame guard (a WAV clip base64s to ~350 KB).

## Files
- `portal/ws_room.py` — relay whitelisted frames (+ size guard).
- `portal/static/intercom.js` — shared module (WS, PTT→`SpeechRecognition`, `SpeechSynthesis` playback, typed `sendText`, routing, `onLocal`/`onStatus`/`onInterim` feedback).
- `portal/static/intercom.css` — PTT buttons, pips, banner.
- **`portal/templates/device_pia.html` + `portal/static/pia_app.js` + `portal/devices/routes.py`** — the bedside **Integrated Com & Alarm** device's Intercom tile is now **hold-to-talk** live audio (the actual bedside surface students use); route passes `room_code`/`encounter_id`.
- `portal/templates/nurse_station.html` + `portal/static/nurse_station.js` — per-bed PTT, page-all, typed fallback, talkback receiver.
- `portal/templates/station.html` + `portal/server.py` (`station_page`) — bedside call button + receiver; route now passes `room_code` / `encounter_id` / `bed_label`.
- `tests/v8/test_intercom_relay.py` — relay, drop-non-whitelisted, room isolation, malformed-ignore.

## Verify
- `tests/v8/test_intercom_relay.py` — 5 passed. Full gate: 1087 passed, 2 skipped.
- Manual (two devices, same room): nurse holds a bed's 🎙 → that bedside hears it;
  nurse holds 📢 → every bedside hears it; bedside holds 📞 → nurse station hears
  it + the bed card pips. Needs HTTPS (mic) + a tap to grant the mic on first use.

## Field-test resolution (FR-016b on-device, 2026-06-26)
On-device testing (iPad Safari + Android Chrome) surfaced four bugs, all fixed in
`portal/static/intercom.js`:
1. **PTT hold dropped on touch.** `pointerleave`/`pointercancel` ended the hold on
   the slightest finger drift (and `setPointerCapture` made it blink). Fixed:
   `touch-action:none` + release only on a document-level `pointerup`, so the hold
   stays engaged while the finger is down regardless of drift.
2. **tx "on" but no media (unreliable renegotiation).** The mic was added to an
   already-negotiated peer and flipped to send, which renegotiated unreliably.
   Fixed: capture the mic FIRST and gate `rtc_hello` on it, so every peer is built
   **sendrecv from the start** (no renegotiation). Mic is captured on the first tap.
3. **Android stuck at `cs=new`.** (a) the mic track was added *before*
   `onnegotiationneeded` was wired, so the offer fired into the void → add the
   track **last**, after the handlers; (b) the no-arg `setLocalDescription()` isn't
   supported on older Android Chrome → use explicit `createOffer()/createAnswer()`.
4. **Station never answered a bed (identity churn).** The station's WebRTC id is
   randomized on every page reload; a bed that cached an old id addressed its offer
   to a now-dead id and the live station dropped it. Fixed: a station accepts ANY
   `nurse:`-addressed signaling (a room has one station); beds stay strict so they
   never grab another bed's traffic. **NB:** the station page must be reloaded to
   pick up client-JS fixes — reloading only the beds is not enough.

A hidden connection-diagnostic overlay (per-peer `cs/ice/ss`, offer/answer/ICE
counts, `rx`/`tx`) is available with **`?icdiag=1`** in the URL (or `localStorage
icdiag=1`) for future field triage — off by default, no overlay in normal use.

## Known gaps / follow-ons
- **Bedside coverage:** wired on the **PIA "Integrated Com & Alarm" device**
  (the primary bedside surface) + the per-bed **chat station** (`station.html`) +
  the nurses station. The **patient avatar app** (`/face/…`, VRAI Faces) is the
  one remaining patient-room surface without an intercom mount — add it there if
  the avatar tablet should also receive/return pages.
- STT is the browser Web Speech API (cloud on Chrome/Safari) — fine for staff
  intercom chatter, but a future on-device STT swap would keep it fully local
  (ties into the on-device-speech research).
- Live transcript is shown + spoken but **not persisted** to the chart/debrief
  log yet — add an `ehr_db` write (or reuse `comm.intercom`) for an audit trail.
- Mic-permission readiness check (warn before a PTT press finds the mic blocked).
