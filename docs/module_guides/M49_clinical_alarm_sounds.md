# M49 — Clinical alarm sounds on the Nursing Station + shared audio asset library

**Phase:** Phase 7 follow-on (post-M48, operator-supplied assets)
**Status:** **DONE**
**Blocked by:** M26 (alarm bus), M27 (Nursing Station), M48 (threshold alarms)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

The operator dropped 15 production-ready clinical-alarm WAV files
into a sibling folder
(`~/Documents/Claude/Projects/Multipatient multi student simualtion/
sounds/clinical_alarms/`) with a manifest naming each file by its
clinical context (priority + metric). M49 imports them into the
project as a shared static asset library and wires them into the
Nursing Station's alarm board so each new alarm plays the right
clinical-alarm tone — same as a real bedside monitor.

The 15 files cover:

| File | Purpose |
|------|---------|
| 01 | Bed exit alarm — patient-side warble |
| 02 | Call bell — patient room chime |
| 03 | Code blue — emergency response cue |
| 04 / 08 / 12 | ECG waveform alarm — HIGH / MEDIUM / LOW |
| 05 / 09 / 13 | Heart rate alarm — HIGH / MEDIUM / LOW |
| 06 / 10 / 14 | SpO₂ alarm — HIGH / MEDIUM / LOW |
| 07 / 11 / 15 | Respiratory rate alarm — HIGH / MEDIUM / LOW |

Severity → priority mapping:

| Alarm severity | Audio priority bucket |
|----------------|----------------------|
| critical       | high                 |
| warning        | medium               |
| info (default) | low                  |

## 2. Structure

**Files added:**

- `portal/static/sounds/clinical_alarms/*.wav` (15 files +
  `MANIFEST.txt`) — copied from the operator's drop folder.
- `portal/alarm_sounds.py` (new) — mapping module:
  - `severity_to_priority(severity)` → "high" / "medium" / "low"
  - `audio_url_for(alarm)` — picks the right WAV path based on
    `source`, `metric`, `kind`, `severity`. Returns `None` when
    no curated WAV matches (UI silently skips audio for that
    alarm).
  - `annotate(alarms)` — mutates each alarm dict in-place to add
    `audio_url` + `audio_priority` fields. Returns the list.

**Files touched:**

- `portal/alarms.py` — `active_alarms(room)` now calls
  `alarm_sounds.annotate(out)` before returning so every alarm
  in the response carries `audio_url` (or None).

- `portal/static/nurse_station.js`:
  - `renderAlarmBoard(alarms)` calls a new `_playNewAlarmSounds`
    helper before rendering.
  - `_playNewAlarmSounds(alarms)` plays each alarm's `audio_url`
    via a freshly-built `Audio()` element at volume 0.8.
  - A module-scoped `_seenAlarmIds` set dedupes: an alarm fires
    its WAV once per occurrence. When the alarm leaves the active
    list, its id is removed from the seen set — so a recurrence
    fires the sound again.
  - When the alarms list goes empty, the seen set is cleared.
  - The `.play()` Promise's `.catch()` swallows the autoplay-
    policy rejection silently (first user gesture unlocks audio).

**No backend schema migration. No new dataclass field.** The audio
fields are computed at read time from data already on the alarm
dict.

## 3. Uses

### 3.1 Alarm → sound mapping

```
Source       Metric / Kind            Severity     → File
─────────────────────────────────────────────────────────────────
threshold    hr                       critical     → 05 (HR HIGH)
threshold    hr                       warning      → 09 (HR MEDIUM)
threshold    hr                       info         → 13 (HR LOW)
threshold    spo2                     critical     → 06 (SpO₂ HIGH)
threshold    spo2                     warning      → 10
threshold    spo2                     info         → 14
threshold    rr                       critical     → 07
threshold    rr                       warning      → 11
threshold    rr                       info         → 15
threshold    rhythm                   critical     → 04 (ECG HIGH)
threshold    rhythm                   warning      → 08
threshold    rhythm                   info         → 12
scene        code.blue                critical     → 03 (code blue)
scene        vitals.drop              <severity>   → HR family
device       alarm.injected.call_bell <severity>   → 02 (call bell)
device       alarm.injected.bed_alarm <severity>   → 01 (bed exit)
device       alarm.injected.code_blue <severity>   → 03 (code blue)
device       pump.alarm / cabinet alarm           → None (device's own audio)
*            unknown                              → None
```

The mapping is intentionally permissive — alarms that don't have
a curated WAV get `audio_url=None` and the UI silently skips audio
for them (the visual badge still flashes).

### 3.2 Dedupe semantics

The Nursing Station polls `/api/room/alarms` every 3 s. Without
dedupe, an unresolved breach (e.g. SpO₂ still 84 → still alarming)
would re-play the WAV on every tick — operator hears a continuous
loop of the same sound.

`_seenAlarmIds` is a `Set<string>` of `alarm_id` values we've
already played the sound for. On each tick:
1. Mark every alarm currently in the active list as `active`.
2. For each active alarm, if its id is NOT in `_seenAlarmIds` →
   play the WAV, add to seen set.
3. For each id in `_seenAlarmIds` that's NOT in active → drop it
   (so a re-occurrence later fires the sound again).
4. When the active list goes empty, clear the entire seen set.

### 3.3 Browser autoplay policy

The first `Audio(...).play()` on a page may be silently rejected
by Chrome/Safari if the user hasn't interacted with the page yet
(autoplay policy). M49 catches the Promise rejection silently so
the failure doesn't cascade. The first time the supervisor clicks
ANYWHERE on the page (e.g. a Clear button), audio unlocks for the
rest of the session.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `alarm_sounds.severity_to_priority(s)` | `portal/alarm_sounds.py` | Maps "critical/warning/info" → "high/medium/low". |
| `alarm_sounds.audio_url_for(alarm)` | same | Returns the WAV URL for an alarm dict, or None. |
| `alarm_sounds.annotate(alarms)` | same | In-place mutator that adds `audio_url` + `audio_priority` to every alarm. |
| `_playNewAlarmSounds(alarms)` | `portal/static/nurse_station.js` | Audio-dispatch + dedupe. |

## 5. Limitations

- **No volume / mute control.** Volume is hard-coded to 0.8.
  A future M50 could add per-room volume + a mute toggle on the
  Nursing Station settings card.
- **Sounds play only on the Nursing Station.** Per-Patient Console
  could ALSO play them (it has its own alarm visibility via the
  M48 threshold-breach feed), but operator workflow today is
  one supervisor at the nurses station + instructor on the
  console (silent). If operators ask for sounds on the console
  too, the same `_playNewAlarmSounds` pattern drops in.
- **Pump/cabinet device alarms keep their existing audio.** Those
  are played by the device tablet's own engine.handle event push
  via the device WS — `alarm_sounds.audio_url_for` returns None
  for them so the nursing station doesn't duplicate the sound.
- **No sound for newly-bound device events** (e.g. a device
  joined the room). Out of scope; we only sound the alarms.
- **Browser autoplay policy** may delay the very first alarm
  sound until the supervisor clicks somewhere. After the first
  user gesture audio unlocks for the session. Mitigation: the
  visual alarm badge always shows immediately regardless of
  audio.
- **The WAVs are large** (~176 KB each, 2.6 MB total). Acceptable
  for a LAN install; if the operator deploys to a remote tablet
  the first load adds ~2.6 MB. Each WAV is cached by the browser
  after first play.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_clinical_alarm_sounds.py::test_clinical_alarm_wavs_shipped` | All 15 WAV files + MANIFEST.txt present in `portal/static/sounds/clinical_alarms/` | PASS | 2026-05-27 |
| `…::test_severity_to_priority_mapping` | critical→high, warning→medium, info→low | PASS | 2026-05-27 |
| `…::test_audio_url_for_threshold_hr_critical` | HR breach @ critical → file 05 | PASS | 2026-05-27 |
| `…::test_audio_url_for_threshold_spo2_critical` | SpO₂ breach @ critical → file 06 | PASS | 2026-05-27 |
| `…::test_audio_url_for_threshold_rr_warning` | RR warning → file 11 (medium) | PASS | 2026-05-27 |
| `…::test_audio_url_for_threshold_rhythm_mapped_to_ecg_family` | Dangerous rhythm → ECG family WAV | PASS | 2026-05-27 |
| `…::test_audio_url_for_scene_code_blue` | scene + code.blue → file 03 | PASS | 2026-05-27 |
| `…::test_audio_url_for_device_call_bell` | device + call_bell → file 02 | PASS | 2026-05-27 |
| `…::test_audio_url_for_device_bed_alarm` | device + bed_alarm → file 01 | PASS | 2026-05-27 |
| `…::test_audio_url_none_for_pump_alarm` | Pump alarms get None (device owns audio) | PASS | 2026-05-27 |
| `…::test_audio_url_none_for_unknown_alarm` | Unknown shape → None, no crash | PASS | 2026-05-27 |
| `…::test_annotate_adds_audio_fields_to_all_alarms` | `annotate` mutates in-place; adds both audio fields | PASS | 2026-05-27 |
| `…::test_room_alarms_response_carries_audio_url_per_alarm` | `/api/room/alarms` JSON carries `audio_url` + `audio_priority` per alarm; SpO₂ critical → file 06 | PASS | 2026-05-27 |
| `…::test_static_wav_route_serves_actual_file` | The static handler serves the WAV bytes (RIFF header + audio/* content-type) | PASS | 2026-05-27 |
| `…::test_nurse_station_js_plays_audio_url_on_new_alarm` | JS dispatcher uses `new Audio(url)` + `.play()` driven by `a.audio_url` | PASS | 2026-05-27 |
| `…::test_nurse_station_js_dedupes_by_alarm_id` | `_seenAlarmIds` set + add/has/delete pattern present | PASS | 2026-05-27 |
| **Full v7 suite** | **359 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M49: copied 15 WAV files + MANIFEST into `portal/static/sounds/clinical_alarms/`; new `portal/alarm_sounds.py` with mapping helpers; alarms.py annotates each alarm; nurse_station.js plays + dedupes; 16 new tests | `portal/static/sounds/clinical_alarms/` (15 files + MANIFEST.txt), `portal/alarm_sounds.py` (new), `portal/alarms.py`, `portal/static/nurse_station.js`, `tests/v7/test_clinical_alarm_sounds.py` (new) |

## 8. Open questions / known issues

- **Volume + mute control on the Nursing Station.** Today
  hard-coded volume=0.8. A future M50 could add an operator-
  facing volume slider + a temporary mute toggle (mutes for N
  seconds, then auto-unmutes so a critical alarm isn't missed).
- **Sounds on the Per-Patient Console.** Same `audio_url` field
  is now in the alarm response; an instructor console could also
  play sounds if operators want it. Today only the Nursing
  Station plays — the instructor's console is silent because the
  instructor is usually focused on chat/scene injection.
- **Per-encounter audio routing in a single browser.** If two
  encounter consoles are open in two tabs, both will play
  sounds. Acceptable; matches real bedside monitor distribution
  where each station has its own speakers.
- **Asset compression.** The WAV files are uncompressed PCM.
  Converting to MP3 or OGG would cut the asset payload by ~10×.
  Out of scope for v7.0 — the WAVs play instantly with no decode
  latency, which matters more for alarm response time than
  bandwidth.
- **Audio cue for ALARM CLEARED.** Currently silent on clear.
  Future M50 could add a brief acknowledgement chime when the
  supervisor clears an alarm.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
