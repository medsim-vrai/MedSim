# M48 — Nurses-station alarm thresholds + per-metric cadence + ECG cosmetic fix

**Phase:** Phase 7 follow-on (post-M47, operator feature request)
**Status:** **DONE**
**Blocked by:** M22 (Per-Patient Console), M23 (telemetry snapshot), M24 (ECG waveform library), M26 (alarm bus), M27 (Nursing Station)
**Blocks:** none
**Estimated effort:** 0.75 day

---

## 1. Purpose

Three operator asks bundled in one paragraph:

> "Alarm levels set on nurses station: Heart rate, O2 sat,
> Respiration, Dangerous wave forms.  BP update unless injected,
> update every 2 minutes, temp every minute, respirations every
> 30 seconds, pulse ox every 10 seconds.  ECG trace line needs to
> be thinner and not look like its glowing."

Delivered:

1. **Operator-settable alarm thresholds on the Nursing Station.**
   New settings card on the supervisor page (`nurse_station.html`)
   for low/high bounds on HR, SpO₂, RR plus a "dangerous
   waveforms" checkbox list (v-fib, v-tach, asystole, a-fib RVR,
   3° block). Thresholds live on `room.alarm_thresholds` (in-
   memory, room-level). The alarm bus (`alarms.py`) checks every
   encounter's telemetry snapshot against these on every
   `/api/room/alarms` tick; breaches surface as
   `source=threshold` alarms in the existing alarm board.

2. **Per-metric display refresh cadence** on the encounter
   console: HR/SpO₂ every 10 s, RR every 30 s, temp every 60 s,
   BP every 120 s. The server poll still runs every 1 s
   (TELEMETRY_POLL_MS unchanged), but the client only COMMITS the
   displayed value at each metric's cadence — matching real
   bedside monitor refresh rates. Operator scene/inject /
   override forces immediate refresh because the latest server
   value differs from the last committed value.

3. **ECG trace cosmetic fix**: stroke-width `1.4 → 0.7`, color
   `#5dffae` (saturated neon) → `#7fc99a` (muted green). Removes
   the glow effect; trace looks like a real bedside monitor.

## 2. Structure

**Files touched:**

- `portal/control_room.py` — `ControlRoom` gets `alarm_thresholds:
  dict[str, Any]` with sensible adult-norm defaults:
  ```python
  {"hr":   {"low": 50,  "high": 120},
   "spo2": {"low": 90,  "high": None},
   "rr":   {"low": 8,   "high": 30},
   "dangerous_rhythms": ["vfib", "asystole", "vtach"]}
  ```

- `portal/alarms.py` — `active_alarms(room)` now merges in
  threshold-breach alarms from a new `_threshold_alarms_for(room,
  enc)` helper. The helper:
  1. Pulls the encounter's telemetry via `telemetry.snapshot(enc.id,
     jitter=False)` (deterministic so threshold checks don't
     oscillate across the boundary).
  2. For each of HR/SpO₂/RR, checks against the room's bounds
     dict. Below `low` or above `high` raises an alarm. SpO₂
     breaches are `severity=critical`; HR/RR are `warning`.
  3. For ECG: if `enc.ecg_enabled` AND `enc.ecg_rhythm_id` is in
     the room's `dangerous_rhythms` list → critical alarm.
  - Threshold alarms use `ts=0` so they always sort to the END of
    their severity bucket — actual device/scene alarms (with a
    real timestamp) keep the top of the alarm board. This
    preserves the M26 alarm-bus invariants.

- `portal/server.py` — two new routes:
  - `GET /api/room/alarm_thresholds` — read current room
    thresholds.
  - `POST /api/room/alarm_thresholds` — operator updates them.
    Body is a partial dict (any key absent is left untouched).
    Numeric coercion + sanity-check on each bound.

- `portal/templates/nurse_station.html` — new
  `<section class="ns-thresholds">` between the alarm board and
  the bed grid. Form with HR/SpO₂/RR low+high inputs +
  dangerous-rhythm checkboxes (data-danger attribute).

- `portal/static/nurse_station.js` — `loadThresholds()` GETs and
  pre-fills the form on page load; `saveThresholds(ev)` POSTs on
  submit. Both wired via the DOMContentLoaded handler.

- `portal/static/nurse_station.css` — new `.ns-thresholds`,
  `.threshold-row`, `.threshold-label`, `.ns-btn-primary` styles
  (dark theme matching the supervisor view).

- `portal/static/ecg_strip.js` — `stroke-width '1.4' → '0.7'`,
  color `#5dffae` → `#7fc99a` for both path stroke + label fill.

- `portal/static/encounter_console.css` — `.ecg-canvas` text
  color also bumped from `#5dffae` to `#7fc99a` so the
  placeholder text + label match the new trace.

- `portal/static/encounter_console.js` — Telemetry rewrite:
  - New `METRIC_CADENCE_MS` table per metric (hr/sbp/dbp/spo2/rr/temp_f).
  - New `_committed` + `_committedAt` per-metric state.
  - New `_maybeCommit(metric, value, now)` helper — commits when
    cadence elapsed OR value changed (inject/override).
  - `pollTelemetry()` reads each metric's committed value
    instead of the raw server reading.

## 3. Uses

### 3.1 Operator sets thresholds

1. Operator opens the Nursing Station (`/portal/control/launch_
   nurse_station` from the master, or scans the QR).
2. Scrolls to "Alarm thresholds" card. Defaults are pre-filled.
3. Types new bounds (e.g. HR 60-100 instead of 50-120).
4. Ticks the "v-fib" + "v-tach" + "asystole" boxes (the default
   dangerous list).
5. Clicks **Save thresholds**. POST round-trip; status text
   confirms "saved · 14:32:18".

### 3.2 Breach surfaces on the alarm board

1. Some time later a scene drops Bed 2's SpO₂ to 84.
2. Next `/api/room/alarms` tick (the Nursing Station polls every
   3 s) the room calls `_threshold_alarms_for(room, bed2)`, which
   resolves SpO₂=84 < 90 → critical alarm "SpO₂ low (84 < 90)".
3. The alarm shows up on the supervisor alarm board sorted under
   real-time scene/device criticals.
4. When the operator re-injects vitals back to SpO₂=95, the
   threshold breach goes away on the next read — no operator
   click required (auto-resolves when the underlying value
   returns to range).

### 3.3 Per-metric display cadence

The Per-Patient Console telemetry strip used to refresh every
metric every 1 s. After M48:
- HR + SpO₂ commit every 10 s (close to continuous).
- RR commits every 30 s.
- Temp commits every 60 s.
- BP commits every 120 s.

When the operator injects a `vitals.drop` scene OR sets an
override, the server value changes — the client's commit logic
notices the diff and refreshes immediately, regardless of cadence.

### 3.4 ECG before / after

| | Pre-M48 | Post-M48 |
|---|---------|----------|
| stroke-width | 1.4 | 0.7 |
| stroke color | `#5dffae` (saturated neon green) | `#7fc99a` (muted green) |
| visual | "glowing" against dark canvas | natural monitor trace |

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `ControlRoom.alarm_thresholds` | `portal/control_room.py` | Room-level thresholds dict. |
| `GET /api/room/alarm_thresholds` | `portal/server.py` | Read current room thresholds. |
| `POST /api/room/alarm_thresholds` | `portal/server.py` | Operator updates. Partial dict body. |
| `_threshold_alarms_for(room, enc)` | `portal/alarms.py` | Internal helper that emits the threshold-breach alarm list. |
| `METRIC_CADENCE_MS` + `_maybeCommit` | `portal/static/encounter_console.js` | Per-metric refresh cadence on the encounter console. |

## 5. Limitations

- **No engine-side vitals drift.** Pre-M48 the engine's value
  doesn't drift naturally — it only changes on scene inject or
  override. M48 adds *display cadence* (commit-on-cadence) but
  not *value drift*. So between injects, the BP display "refreshes"
  every 2 minutes but commits the same value — visually no change.
  Realistic medical drift (HR ±2, SpO₂ ±1 over a few minutes) is
  M49 territory and requires a server-side ticker that calls
  `_apply_drift()` per metric per cadence.
- **Thresholds are room-level, not per-encounter.** A high-risk
  patient and a stable post-op share the same thresholds. The
  operator can adapt by tuning bounds wider/tighter. A future
  M49 could add a per-encounter override layer.
- **Threshold alarms can't be cleared.** Unlike device/scene
  alarms (which have an explicit `/api/alarm/{id}/clear` route),
  threshold alarms auto-resolve when the underlying value
  returns to range. Operators can SILENCE the cause (raise
  bound, inject correction) but not "clear" the breach itself.
  Documented; matches real bedside monitor semantics.
- **Dangerous rhythm detection is binary.** Either the
  encounter's `ecg_rhythm_id` is in the danger list or it isn't.
  Real monitors detect arrhythmias from the waveform (e.g.
  detected v-tach episode mid-recording). The v7 model is
  simulation-driven so this binary check matches the rhythm-
  picker UX.
- **Cadence is hard-coded** in JS. A future operator-facing
  setting could let supervisors tune their preferred refresh
  rates. Out of scope today.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_alarm_thresholds_and_ecg_fix.py::test_thresholds_get_returns_defaults` | Default thresholds round-trip from GET | PASS | 2026-05-27 |
| `…::test_thresholds_post_updates_and_persists` | POST update reflects on next GET | PASS | 2026-05-27 |
| `…::test_thresholds_post_rejects_non_numeric_bound` | Bad number → 400 | PASS | 2026-05-27 |
| `…::test_threshold_breach_surfaces_on_room_alarms` | HR override > high → alarm in room feed with `source=threshold` | PASS | 2026-05-27 |
| `…::test_threshold_breach_spo2_is_critical` | SpO₂ breaches are critical-severity | PASS | 2026-05-27 |
| `…::test_threshold_breach_below_low_bound` | Below-low bound also alarms | PASS | 2026-05-27 |
| `…::test_threshold_dangerous_rhythm_raises_when_ecg_enabled` | Rhythm alarm only when ECG enabled; toggling off clears it | PASS | 2026-05-27 |
| `…::test_ecg_trace_uses_thinner_stroke_and_muted_color` | stroke-width=0.7, color=#7fc99a | PASS | 2026-05-27 |
| `…::test_ecg_canvas_color_matches_trace` | Canvas text color matches new muted green | PASS | 2026-05-27 |
| `…::test_encounter_console_js_has_per_metric_cadence_table` | METRIC_CADENCE_MS table + _maybeCommit + _committed.* present | PASS | 2026-05-27 |
| `…::test_nurse_station_renders_threshold_form` | Nurse Station HTML carries the threshold-settings form with all 6 inputs + dangerous-rhythm checkboxes | PASS | 2026-05-27 |
| **Full v7 suite** | **343 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M48: ControlRoom.alarm_thresholds + 2 routes + alarms.py `_threshold_alarms_for`; Nurse Station threshold settings card; per-metric cadence display on the encounter console; ECG stroke + color cosmetic fix; 11 new tests | `portal/control_room.py`, `portal/alarms.py`, `portal/server.py`, `portal/templates/nurse_station.html`, `portal/static/nurse_station.{js,css}`, `portal/static/encounter_console.{js,css}`, `portal/static/ecg_strip.js`, `tests/v7/test_alarm_thresholds_and_ecg_fix.py` (new) |

## 8. Open questions / known issues

- **Engine-side vitals drift** is the biggest missing piece (see
  §5). A future M49 would add a `_apply_drift(enc)` ticker called
  from the existing alarm-bus poll (or its own task) that
  randomly walks HR ±1, SpO₂ ±0 (rare), RR ±0.5 etc per cadence.
  Operator inject still wins because the simulation writes a
  fresh vitals.record that overrides drift.
- **Per-encounter threshold override** — a high-risk patient may
  warrant tighter bounds than a stable post-op. A future
  refinement could add `enc.alarm_thresholds_override: dict |
  None` that, if set, layers on top of the room defaults. Out of
  scope for M48.
- **Threshold breaches in the cohort debrief.** The M14 PEARLS
  debrief reads the chart_event log. Threshold-breach alarms
  aren't currently written to that log — they're computed from
  the telemetry snapshot at read time. A future module could
  also emit a `vitals.breach` chart_event so the debrief shows
  the breach timeline.
- **Operator-facing settings persistence**. Thresholds reset on
  server restart (room dies, in-memory state goes with it). A
  future M49 could persist thresholds to SQLite alongside other
  room state.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
