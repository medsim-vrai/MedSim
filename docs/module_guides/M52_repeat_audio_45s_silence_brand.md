# M52 — Repeating alarm audio + 45 s silence default + brand rename

**Phase:** Phase 7 follow-on (post-M51, operator feedback)
**Status:** **DONE**
**Blocked by:** M49 (alarm sounds), M50 (silence), M51 (PIA cascade), M41 (print sheet)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Three asks from the operator, bundled:

> "Repeat alarm sounds until cleared, silence of an alarm last 45
> seconds then it goes active if the condition is not resolved or
> cleared. Branding on screens and printed material- 'Training
> Bridge VRAI- MedSim'"

Delivered:

1. **Repeating alarm audio** on the Nursing Station and on the PIA
   cascade. M49 played each alarm's WAV exactly ONCE on first sight
   (good enough for a demo but unsafe for a real drill — the operator
   could miss the only chime). Now the audio dispatcher keeps a
   per-alarm last-played timestamp and replays on a cadence matched
   to the priority field already on every alarm:
   - **high** (critical + danger): every 8 s
   - **medium** (warning): every 20 s
   - **low** (info): every 45 s
   PIA's code-blue cascade poller uses a fixed 8 s repeat. Silenced
   alarms skip the play call but the timestamp tracking continues.
2. **45 s silence default**. M50 shipped silence with a 120 s default;
   operator wants 45 s so the alarm gets a chance to re-fire if the
   underlying breach hasn't resolved. The route's `?seconds=N`
   override still works for the rare case an operator wants longer.
3. **Brand rename**. Every user-visible screen title + the printable
   QR sheet now reads **"Training Bridge VRAI- MedSim"** (exact
   spacing per operator). Code-level identifiers (window.MEDSIM2_OPS,
   `~/.medsim/` filesystem path, `medsim_ehr_window` browser
   target) are left alone — those are code, not user-visible brand.

---

## 2. Files touched

### Server
- `portal/alarms.py` — `silence_alarm` helper default `duration_s` 120 → 45.
- `portal/server.py` — `POST /api/alarm/{id}/silence` route `seconds: int = 120` → `45`. Comment updated.

### Client JS
- `portal/static/nurse_station.js`
  - Replaced `_seenAlarmIds: Set` with `_audioLastAt: Map<alarm_id, ms>`.
  - Added `AUDIO_REPEAT_MS = {high: 8000, medium: 20000, low: 45000}`.
  - Re-write `_playNewAlarmSounds(alarms)` to consult `audio_priority`, pick the cadence, replay when `(now - last) ≥ cadence`, skip silenced alarms, and drop ids that leave the active list.
  - Silence button title now reads "Mute audio for 45 s without clearing the breach (audio resumes after if still active)".
- `portal/static/pia_app.js`
  - Added `CASCADE_AUDIO_REPEAT_MS = 8000` + `_cascadeAudioLastAt: Map`.
  - Cascade poller now plays `03_code_blue.wav` every 8 s per active code-blue alarm (gated per alarm_id), while keeping the `_cascadeKey` flash dedupe so the CSS animation doesn't restart on every poll.

### Templates (brand rename)
- `portal/templates/base.html` — `<title>` and topbar brand text.
- `portal/templates/home.html` — `<h1>`.
- `portal/templates/login.html` — `<title>` + `<h1>`.
- `portal/templates/join.html` — `<title>` + `<h1>`.
- `portal/templates/ehr_join.html` — `<title>`.
- `portal/templates/device_app.html` — `<title>` + `apple-mobile-web-app-title` meta.
- `portal/templates/device_join.html` — `<title>` + meta.
- `portal/templates/device_pia.html` — `<title>` suffixed with brand.
- `portal/templates/nurse_station.html` — `<title>` suffixed with brand.
- `portal/templates/qr_print.html` — `<title>` + `.brand-title` h1 (two occurrences).

### Tests
- `tests/v7/test_repeat_audio_silence_brand.py` (new) — 18 acceptance tests covering all three asks.
- `tests/v7/test_clinical_alarm_sounds.py` — `test_nurse_station_js_dedupes_by_alarm_id` was asserting the old once-per-occurrence behaviour. Renamed to `test_nurse_station_js_repeats_audio_by_cadence` and re-pointed at the new `_audioLastAt` / `AUDIO_REPEAT_MS` symbols.
- `tests/v7/test_qr_print_sheet.py` — brand assertion swapped from "Training Bridge MedSim-VRAI" to "Training Bridge VRAI- MedSim".

---

## 3. Acceptance — what M52 must satisfy

Source: `tests/v7/test_repeat_audio_silence_brand.py` (18 tests).

### 3.1 Silence default
- `POST /api/alarm/{id}/silence` with no `?seconds` query lands at 45 s. Response body says `duration_s == 45` and `silenced_until ≈ now + 45`.
- `POST /api/alarm/{id}/silence?seconds=120` still works — operator override preserved.
- `inspect.signature(alarms.silence_alarm).parameters["duration_s"].default == 45`.

### 3.2 Repeating audio on the Nursing Station
JS source must carry:
- `_audioLastAt` (Map identifier).
- `AUDIO_REPEAT_MS` with `high`, `medium`, `low` keys.
- Reads `audio_priority` from each alarm dict.
- Silenced alarms still skipped (`a.silenced`).
- Map cleared when alarms list goes empty.
- Old `_seenAlarmIds` symbol completely gone (code AND comments).

### 3.3 Repeating audio on the PIA cascade
JS source must carry:
- `_cascadeAudioLastAt` Map.
- `CASCADE_AUDIO_REPEAT_MS` constant set to 8000.
- Silenced alarms skipped.
- Map cleared when no code-blue alarms are active.
- `_cascadeKey` retained — flash CSS still gated by NEW alarm sets.
- `playSound('code_blue')` still wired.

### 3.4 Brand on every user-visible screen
- `base.html` contains "Training Bridge VRAI- MedSim" and no "MEDSIM 2".
- Same check for `home.html`, `login.html`, `join.html`, `ehr_join.html`, `device_app.html`, `device_join.html`, `device_pia.html`, `nurse_station.html`.
- `qr_print.html` contains the brand string ≥ 2 times (title + visible header) and zero occurrences of the old "Training Bridge MedSim-VRAI".
- End-to-end HTTP fetch of `/portal/home` and `/portal/control/qr_print` includes the new brand and excludes the old one.

All 18 tests pass; full v7 suite **405 passed, 1 skipped, 0 regressions** (was 387 pre-M52).

---

## 4. Cadence values — why these numbers

The cadence table mirrors real bedside-monitor behaviour:

| Priority | Cadence | Source                                |
|----------|---------|---------------------------------------|
| high     | 8 s     | Critical/danger alarms — short repeat |
| medium   | 20 s    | Warning alarms — moderate             |
| low      | 45 s    | Info alarms (call bell) — gentle      |

The PIA cascade fires at the high rate (8 s) because every code blue
is by definition top-priority. Other PIA presses (`call_bell`,
`bed_alarm`) don't go through the cascade poller — they show as
device alarms on the nurse station and get their own per-priority
cadence there.

**Why not just play continuously?** Bedside students need to be able
to talk over the alarm, communicate with the team, and hear the
nurse station's intercom. A short repeating tone (rather than a
continuous one) leaves space for clinical communication while
keeping the alarm psychologically present.

**Interaction with silence**: a silenced alarm doesn't tick its
last-played timestamp forward — but the silence itself expires
after 45 s by default (down from M50's 120 s). So a worst-case
sequence is:

1. SpO2 dips → audio plays at t=0.
2. Operator silences → audio off, alarm board shows 🔇.
3. 45 s later, silence expires; if breach still active, the audio
   dispatcher sees it un-silenced again on the next poll and
   re-fires at the high cadence.

The operator's stated requirement — *"silence of an alarm last 45
seconds then it goes active if the condition is not resolved or
cleared"* — is satisfied because the silence-record TTL and the
audio-loop repeat are now both wired in.

---

## 5. What was deliberately NOT renamed

- `window.MEDSIM2_OPS`, `window.MEDSIM2_STATION`, `window.MEDSIM2`,
  `window.MEDSIM_SESSION` (JS globals — code-level identifiers
  referenced from .js source files; renaming would silently break
  the bootstrap).
- `~/.medsim/vault.enc` (filesystem path — renaming would lose
  every existing user's vault).
- `target="medsim_ehr_window"` (browser-window target name; matches
  across multiple links so we don't open three EHR tabs).
- `var KEY = 'medsim_a2hs_dismissed_at'` (localStorage key — code).
- "Voice4MedSim_v6" historical attribution in personas/curriculum
  docs (correct attribution of the source).
- `BUILD_STATE.md` and `MODULE_GUIDE_TEMPLATE.md` body text
  (internal engineering docs, not user-facing).

If the operator wants any of those renamed too they're a separate
ticket — each one touches code paths that need migration.

---

## 6. Demo script for the operator

1. Hit `/portal/home` — top-left brand should read **Training Bridge VRAI- MedSim**, browser tab title same. Old "MEDSIM 2" gone.
2. From an active room, click "Print all encounters" — printed sheet header says **Training Bridge VRAI- MedSim** in the top-of-page banner.
3. Force an SpO2 breach (Per-Patient Console → set SpO2 = 80). Within 3 s the Nursing Station should:
   - Play the high-priority chime.
   - Re-play it every ~8 s until cleared.
4. Click 🔇 Silence on that alarm. The chime stops. Wait 45 s. The audio comes back on its own.
5. Click Clear. The chime stops and the alarm disappears.
6. Register a PIA on Bed 1, another on Bed 2. From Bed 1's PIA, hit Code Blue. Both PIAs flash red and play the code-blue tone every ~8 s until the alarm is cleared from the nurse station.

---

**Closes:** the operator's three asks from the M52 message in full.
No follow-on tickets identified.
