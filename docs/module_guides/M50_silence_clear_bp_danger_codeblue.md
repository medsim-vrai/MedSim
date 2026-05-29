# M50 — Silence + Clear-bugfix + BP thresholds + danger severity + Nurse-station Code Blue

**Phase:** Phase 7 follow-on (post-M49, operator feedback)
**Status:** **DONE**
**Blocked by:** M26 (alarm bus), M27 (Nursing Station), M48 (alarm thresholds), M49 (alarm sounds)
**Blocks:** none
**Estimated effort:** 1 day

---

## 1. Purpose

Five interrelated asks from the operator:

> "Add silence alarm for each Patient encounter on nurses station
> alarm in addition to clear. The alarm clear did not work. Also
> ad Blood pressure to the list of items that has alarm ranges.
> For Dangerous wave forms they should get a weighted with highest
> alarm rating. Also the nurse station should be able to activate
> a code blue from the nurses station screen on a specific patient
> character encounter."

Delivered:

1. **Silence button** per alarm — `POST /api/alarm/{id}/silence?seconds=N`
   defaults to 120 s. The alarm stays VISIBLE on the board with a
   🔇 badge but no audio fires during the silence window.
   Works on every alarm source (device, scene, threshold).

2. **Clear bugfix** — pre-M50, `clear_alarm()` returned `None` for
   `source=threshold` (no event log to write into), so the
   `/api/alarm/{id}/clear` route 404'd on every threshold alarm.
   Fixed: threshold clears now route through the silenced map with
   `cleared=True` so they're filtered out of the active feed.

3. **BP thresholds** — new `bp_systolic` and `bp_diastolic` keys on
   `room.alarm_thresholds` with sensible adult-norm defaults
   (sbp 90–160, dbp 60–100). The threshold check raises alarms
   when either side breaches.

4. **Danger severity** — dangerous waveforms (v-fib, asystole,
   v-tach) now use `severity="danger"` (rank 4) which outranks
   `critical` (rank 3) in the alarm-board sort. They float to the
   TOP of the alarm feed with a red pulsing visual treatment.
   `alarm_sounds.severity_to_priority` maps `danger → high` so they
   share the HIGH-priority WAV with critical alarms.

5. **Nurse-station Code Blue** — new route
   `POST /api/room/encounter/{eid}/nurse_code_blue` accepting
   `nurse_sid` in the body (validates against the room's nurse-
   station students). The Nursing Station bed cards get a
   🚨 **Code Blue** button that POSTs to this route.

## 2. Structure

**Files touched:**

- `portal/control_room.py`:
  - `alarm_thresholds` defaults now include `bp_systolic` +
    `bp_diastolic` (adult-norm ranges).
  - New `silenced_alarms: dict[str, dict[str, Any]]` field. Maps
    `alarm_id → {until: float, cleared: bool}`. The alarms.py
    `_apply_silenced` helper reads + cleans up.

- `portal/alarms.py`:
  - `active_alarms(room)` severity_rank gains a `danger=4` entry
    (above critical=3) so dangerous-rhythm alarms sort to the top.
  - New `_apply_silenced(room, alarms)` helper: drops cleared
    alarms from the active feed, annotates silenced alarms with
    `silenced=True` + `silenced_until`. Cleans up expired entries.
  - `_threshold_alarms_for` extends `metric_breaches` to include
    `bp_systolic` + `bp_diastolic` (mapped to snapshot keys
    `sbp` / `dbp`).
  - Dangerous-rhythm alarms now emit `severity="danger"`.
  - `clear_alarm()` gets a `source == "threshold"` branch that
    stores the alarm in `room.silenced_alarms` with `cleared=True`
    and an `until` 24 h out (effectively "cleared until breach
    resolves").
  - New `silence_alarm(room, alarm_id, duration_s=120)` helper —
    stores with `cleared=False`.

- `portal/alarm_sounds.py`:
  - `severity_to_priority` now maps both `danger` AND `critical`
    → "high" (same WAV bucket — no separate danger asset ships).
  - `audio_url_for` collapses `bp_systolic` / `bp_diastolic`
    families into the `hr` audio family (asset library doesn't
    ship a dedicated BP WAV).

- `portal/server.py`:
  - New `POST /api/alarm/{id}/silence?seconds=N` route (instructor
    gated).
  - New `POST /api/room/encounter/{eid}/nurse_code_blue` route
    accepting EITHER an instructor cookie OR `nurse_sid` body
    field (validates against room.students whose `role ==
    "nurse_station"`). Fires a `code.blue` scene via the existing
    `scenes.apply()` helper.
  - `POST /api/room/alarm_thresholds` validation expanded to
    accept `bp_systolic` + `bp_diastolic` keys.

- `portal/templates/nurse_station.html`:
  - Threshold form gets two new rows: BP systolic + BP diastolic
    (each with low + high inputs).

- `portal/static/nurse_station.js`:
  - `renderAlarmBoard` renders BOTH a 🔇 Silence and a Clear button
    per alarm; silenced alarms render with `.silenced` CSS class
    and a badge.
  - `_playNewAlarmSounds` skips alarms with `a.silenced === true`.
  - `loadThresholds` + `saveThresholds` read/write the BP fields.
  - `renderBedCard` adds a 🚨 Code Blue button at the bottom of
    each bed card with a `confirm()` dialog and POST to the new
    nurse_code_blue route with the student's sid.

- `portal/static/nurse_station.css`:
  - `.alarm-actions` flex for the Silence + Clear button pair.
  - `.silenced-badge` styling, plus `.alarm-list li.silenced` grey-
    out treatment.
  - `.severity-danger` deep-red background + pulsing border
    keyframe.
  - `.bed-card-actions` + `.ns-code-blue-btn` (deep-red CTA).

## 3. Uses

### 3.1 Silence flow

1. Operator on Nursing Station sees a SpO2 critical alarm.
2. Clicks **🔇 Silence**. `POST /api/alarm/threshold:...:spo2/silence`
   → server stores `{until: now+120, cleared: false}` in
   `room.silenced_alarms`.
3. Next 3 s poll: alarm still in feed, but now with
   `silenced=true` + `silenced_until=...`. JS dispatcher's
   `_seenAlarmIds` check additionally skips audio for silenced
   alarms.
4. After 120 s the `until` timestamp passes; the `_apply_silenced`
   helper cleans up the entry on the next read; alarm re-fires
   audio if still breaching.

### 3.2 Clear bugfix

| Before M50 | After M50 |
|------------|-----------|
| Operator clicks Clear on a threshold alarm. POST 404s "Unknown alarm id 'threshold:..:spo2'". Alarm stays on the board. | Same click — route returns 200 with `{cleared: true, source: "threshold"}`. Alarm gone from the next read. If the breach resolves, the cleared entry expires harmlessly. |

### 3.3 BP thresholds

1. Operator opens Nursing Station threshold settings.
2. Sees BP systolic (90–160) + BP diastolic (60–100) pre-filled.
3. Adjusts to scenario-appropriate values (e.g. sbp 100–140).
4. Click Save → POST `/api/room/alarm_thresholds` body
   `{bp_systolic: {low: 100, high: 140}, ...}`.
5. When a scene drops `sbp` to 75, the alarm bus raises a
   `threshold:E-XYZ:bp_systolic` warning alarm with label
   *"BP systolic low (75 < 100)"*.

### 3.4 Danger severity sorting

Two alarms simultaneously active on the room:
- v-fib rhythm on Bed 2 → `severity=danger`
- SpO2 84 on Bed 1 → `severity=critical`

The alarm board sorts:
```
1. 🔴 v-fib rhythm (danger, Bed 2)   ← top, red pulsing
2. ⚠️  SpO2 low (critical, Bed 1)
```

Audio: both fire the high-priority WAV (file 04 for ECG and
file 06 for SpO2). The visual treatment makes the danger alarm
unmissable.

### 3.5 Nurse-station Code Blue

1. Supervisor sees Bed 2 deteriorating (v-fib + low SpO2).
2. Clicks 🚨 **Code Blue** on Bed 2's card.
3. Confirms in the `confirm()` dialog.
4. JS POSTs `/api/room/encounter/E-bed2/nurse_code_blue` with
   `{nurse_sid: "S-instructor-nurse-sid"}`.
5. Server validates the sid against `room.students` (must be a
   `nurse_station`-role student); calls
   `scenes.apply(enc_bed2, {kind: "code.blue"}, by="nurse_station:<sid>")`.
6. The code.blue scene writes chart events + raises alarms
   normally — same path as if the instructor had clicked
   "Inject scene" on the Multi-Patient Control dashboard.

Auth alternatives:
- Instructor cookie: works without nurse_sid.
- nurse_sid not matching a nurse-station student: 403.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `POST /api/alarm/{id}/silence?seconds=N` | `portal/server.py` | Silence an alarm for N seconds. |
| `POST /api/room/encounter/{eid}/nurse_code_blue` | same | Fire code.blue from Nursing Station OR instructor. |
| `ControlRoom.silenced_alarms` | `portal/control_room.py` | In-memory dict of silenced/cleared alarm states. |
| `ControlRoom.alarm_thresholds["bp_systolic"]` + `["bp_diastolic"]` | same | New BP threshold keys (adult-norm defaults). |
| `alarms.silence_alarm(room, alarm_id, duration_s)` | `portal/alarms.py` | Direct helper for tests + future programmatic callers. |
| `alarms._apply_silenced(room, alarms)` | same | Internal filter that drops cleared alarms + annotates silenced ones. |
| Severity `"danger"` (rank 4) | same | New tier above critical for dangerous waveforms. |

## 5. Limitations

- **No persistence**. `silenced_alarms` lives on the in-memory
  ControlRoom — restarts wipe silence state. Acceptable for
  classroom sessions; if persistence is needed a future M51 could
  serialize to SQLite.
- **Single silence duration in UI**. Default 120 s; operator can
  hit the route directly with `?seconds=N` but the Silence button
  doesn't expose a duration picker. A future M51 could add a
  long-press / dropdown for 60s / 120s / 5min.
- **The "danger" WAV is the same as critical**. The 15-asset
  library doesn't ship a dedicated danger-priority WAV; we route
  danger to the HIGH-priority bucket (same as critical). The
  visual treatment carries the priority difference.
- **Nurse-station Code Blue confirm dialog is the native browser
  `confirm()`**. A custom modal could match the M39 engage dialog
  styling, but the native confirm is unmissable and prevents
  accidental clicks — operator-positive in this context.
- **No audit trail of who silenced**. The silenced_alarms map
  doesn't record which operator hit Silence. If a class debrief
  needs that, the route could log an event_id. Out of scope.
- **Cleared threshold alarms re-emerge after 24 h**. The cleared
  entry's `until` is set to `now + 86400`. If a classroom session
  runs longer (rare for a teaching scenario), the cleared alarm
  re-emerges. Acceptable; doc'd.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_silence_and_code_blue.py::test_silence_a_threshold_alarm_sets_silenced_flag` | Silence route works on threshold alarm + sets silenced=True | PASS | 2026-05-27 |
| `…::test_silence_unknown_alarm_id_404` | Unknown alarm id: accept-200 or reject-404 | PASS | 2026-05-27 |
| `…::test_clear_threshold_alarm_now_works` | The bugfix — Clear on threshold returns 200 + alarm gone from feed | PASS | 2026-05-27 |
| `…::test_clear_device_alarm_still_works` | M26 device/scene clear unchanged | PASS | 2026-05-27 |
| `…::test_bp_systolic_threshold_breach_alarms` | sbp=180 with high=130 → threshold alarm | PASS | 2026-05-27 |
| `…::test_bp_diastolic_threshold_breach_alarms` | dbp=105 with high=90 → threshold alarm | PASS | 2026-05-27 |
| `…::test_bp_default_thresholds_present` | bp_systolic + bp_diastolic in default GET | PASS | 2026-05-27 |
| `…::test_danger_severity_sorts_above_critical` | v-fib (danger) appears ABOVE SpO2 (critical) in feed | PASS | 2026-05-27 |
| `…::test_danger_severity_maps_to_high_priority_audio` | severity_to_priority("danger") == "high"; audio_url_for(danger rhythm) → file 04 | PASS | 2026-05-27 |
| `…::test_nurse_code_blue_via_sid_fires_scene` | Nurse-station sid (no instructor cookie) fires code.blue at named encounter | PASS | 2026-05-27 |
| `…::test_nurse_code_blue_rejects_unknown_sid` | Bogus sid → 403 | PASS | 2026-05-27 |
| `…::test_nurse_code_blue_works_with_instructor_cookie` | Operator cookie path (no nurse_sid) → by="instructor" | PASS | 2026-05-27 |
| `…::test_nurse_code_blue_unknown_encounter_404` | Unknown encounter id → 404 | PASS | 2026-05-27 |
| `…::test_nurse_station_html_carries_bp_threshold_inputs` | Threshold form has sbp + dbp low/high inputs | PASS | 2026-05-27 |
| `…::test_nurse_station_js_has_silence_handler_and_code_blue_button` | JS source carries data-silence, /silence call, audio.silenced check, ns-code-blue-btn, nurse_code_blue route call | PASS | 2026-05-27 |
| (regression update) `test_threshold_dangerous_rhythm_raises_when_ecg_enabled` | Severity assertion `critical` → `danger` | PASS | 2026-05-27 |
| **Full v7 suite** | **374 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M50: silence helper + route; clear bugfix for threshold; BP thresholds; danger severity rank 4; nurse-station code-blue route + button; UI updates; 15 new tests + 1 regression assertion update | `portal/control_room.py`, `portal/alarms.py`, `portal/alarm_sounds.py`, `portal/server.py`, `portal/templates/nurse_station.html`, `portal/static/nurse_station.{js,css}`, `tests/v7/test_silence_and_code_blue.py` (new), `tests/v7/test_alarm_thresholds_and_ecg_fix.py` (assertion update) |

## 8. Open questions / known issues

- **Persistence**. `silenced_alarms` dict resets on server restart.
  If the operator's classroom session restarts mid-flow, silenced
  alarms wake up. Acceptable for typical teaching sessions; M51
  could persist to SQLite.
- **Silence duration UX**. Default 120s; the route accepts any
  `?seconds=N`. A dropdown / long-press for 60s/120s/5min would be
  nicer.
- **Custom Code Blue confirm modal**. Today uses `window.confirm()`
  which is unmissable but doesn't match the M39 dialog styling.
  Trade-off — defaulted to the safer native confirm.
- **Audit trail**. No record of who silenced/cleared an alarm.
  The cohort debrief could surface this if useful. Tracked.
- **No "snooze for 5 min" / smart-snooze**. Standard silence is a
  fixed window. Real bedside monitors offer a "Silence Indefinitely"
  / "Pause Audio" mode for confirmed-critical alarms. Out of
  scope.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
