# M54 — Collapsible threshold panel + concurrent tiered repeating audio + magnitude-based threshold severity

**Phase:** Phase 7 follow-on (post-M53, operator feedback)
**Status:** **DONE**
**Blocked by:** M48 (thresholds), M49 (sounds), M50 (severity tiers), M52 (repeating audio)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

> "Nursing station- alarm threshold click to drop down and open, click
> header of Alarm threshold and have it roll up. Alarms need to run
> concurrently. For higher priority alarms (low- medium-High) the
> alarms sound more frequently. For example the sound loop for a code
> blue should run continuously with minimal time gap running the sound
> loop. Low level alarms sound when parameters are 10% below lower
> threshold or 10% Higher than upper threshold. Medium is between 10%
> and 20% of threshold limits and high if above 20% of the threshold
> limits"

Four asks bundled:

1. **Collapse / expand the threshold panel** by clicking its header.
2. **Concurrent audio** — multiple alarms play simultaneously.
3. **Tighter, tiered cadence** — code blue near-continuous; lower
   tiers progressively less frequent.
4. **Magnitude-based threshold severity** — 0–10% past bound is
   LOW (info), 10–20% is MEDIUM (warning), >20% is HIGH (critical).

---

## 2. What ships

### 2.1 Collapsible alarm-threshold panel
`portal/templates/nurse_station.html` — the threshold `<section>`
default-collapses with class `ns-collapsed`; the `<h2>` becomes a
role=button toggle (`#ns-thresholds-toggle`) with `aria-expanded`
+ `aria-controls`. A caret span rotates 90° when expanded.

`portal/static/nurse_station.js` — new `wireThresholdToggle()`:
- Click on the H2 → toggles `ns-collapsed` on the section, flips
  `aria-expanded`.
- Keyboard accessible: Enter / Space when focused also toggles.

`portal/static/nurse_station.css` — `.ns-thresholds.ns-collapsed
.ns-thresholds-form { display: none; }` hides the form; the
header stays visible. Caret rotates via a CSS transition.

### 2.2 Audio cadence — four tiers
New table in `nurse_station.js`:

| Tier   | Cadence | Maps to severity            |
|--------|---------|------------------------------|
| danger | 2500 ms | `danger` (code blue, dangerous rhythm) — near-continuous |
| high   | 5000 ms | `critical`                   |
| medium | 15000 ms | `warning`                   |
| low    | 35000 ms | `info`                      |

Pre-M54: `high=8000, medium=20000, low=45000` — tightened across
the board.

The dispatcher's tier-picker reads `severity` first (so `danger`
gets its own bucket even though `severity_to_priority` maps both
critical and danger to `"high"` for the WAV lookup — same WAV file,
different cadence):

```js
function _audioCadenceTier(a) {
  const sev = (a.severity || '').toLowerCase();
  if (sev === 'danger') return 'danger';
  return a.audio_priority || 'medium';
}
```

### 2.3 Fast ticker for the danger tier
The state poll runs every 3 seconds — that's too slow for the 2.5 s
danger cadence. M54 adds a 700 ms `setInterval` that re-runs the
dispatcher against the cached last-alarms list:

```js
let _lastAlarmsForAudio = [];
// pollOnce caches alarms here on every refresh.
setInterval(() => {
  if (_lastAlarmsForAudio && _lastAlarmsForAudio.length) {
    _playNewAlarmSounds(_lastAlarmsForAudio);
  }
}, 700);
```

For non-danger tiers (≥ 5 s cadence) the 3 s poll already gates the
re-fires — the fast ticker is effectively a no-op for them. The 2.5 s
danger tier is the one that benefits.

### 2.4 Concurrent playback
The dispatcher iterates `alarms.forEach(a => { … new Audio(url).play(); })`
— each iteration creates an independent Audio instance, so two
beds in simultaneous breach => two overlapping tones. M54 adds an
explicit `// CONCURRENTLY` comment so future editors don't
accidentally serialise into a queue.

### 2.5 PIA cascade cadence tightened
`portal/static/pia_app.js` — `CASCADE_AUDIO_REPEAT_MS` 8000 → 2500.
Same intent: code blue near-continuous on the bedside tablet.

### 2.6 Magnitude-based threshold severity
`portal/alarms.py::_threshold_alarms_for` now computes
`deviation_pct = (value - bound) / abs(bound) * 100` and maps:

```python
if deviation_pct >= 20.0:
    severity = "critical"     # HIGH tier
elif deviation_pct >= 10.0:
    severity = "warning"      # MEDIUM tier
else:
    severity = "info"         # LOW tier
```

Pre-M54: per-metric fixed severity (SpO2 always critical, others
warning). Now responsive to the depth of the breach — a 1-point
SpO2 dip below threshold is now `info`, a 22%+ dip stays `critical`.

Each threshold alarm dict gains a `deviation_pct: float` field so
the UI could render a "+15% over upper" badge in the future.

### 2.7 Code-blue / code_blue_button promoted to danger
`portal/alarms.py::_SEVERITY_BY_KIND`:
- `"code.blue": "danger"` (was `"critical"`)
- `"code_blue_button": "danger"` (was `"critical"`)

This puts code blue at the top of the sort order AND routes its
audio through the new 2.5 s danger cadence. Same WAV.

---

## 3. Files touched

### Modified
- `portal/alarms.py` — `_SEVERITY_BY_KIND` code.blue + code_blue_button → "danger"; `_threshold_alarms_for` computes magnitude-based severity + adds `deviation_pct` to each alarm.
- `portal/templates/nurse_station.html` — `<section class="ns-thresholds ns-collapsed">` + role=button H2 toggle with ARIA.
- `portal/static/nurse_station.js` — new `wireThresholdToggle()`, four-tier `AUDIO_REPEAT_MS`, `_audioCadenceTier()` helper, 700 ms fast ticker, `_lastAlarmsForAudio` cache, M54 concurrency comment.
- `portal/static/nurse_station.css` — `.ns-thresholds-toggle` + caret + `.ns-collapsed` rules.
- `portal/static/pia_app.js` — `CASCADE_AUDIO_REPEAT_MS` 8000 → 2500.

### New
- `tests/v7/test_collapse_concurrent_tiered_severity.py` — 17 acceptance tests.
- `docs/module_guides/M54_collapsible_concurrent_tiered_severity.{md,pdf}` — this guide.

### Tests updated (intentional contract changes)
- `tests/v7/test_alarm_bus.py` — code.blue severity → danger.
- `tests/v7/test_alarm_thresholds_and_ecg_fix.py` — HR=130 against high=80 → critical (was warning, since 62.5% > 20%); SpO2 deep-drop test deepened to value=70 so it stays in critical under the new magnitude rules.
- `tests/v7/test_clinical_alarm_sounds.py` — SpO2 audio-priority test deepens to 70 to land in the high-priority bucket; cadence regex search window widened to accommodate the larger dispatcher.
- `tests/v7/test_future_devices.py` — code_blue_button severity → danger.
- `tests/v7/test_repeat_audio_silence_brand.py` — PIA cascade cadence now 2500 (was 8000).

---

## 4. Acceptance

Source: `tests/v7/test_collapse_concurrent_tiered_severity.py` (17 tests).

### 4.1 Magnitude-based severity
- HR.high=100, v=105 → info, deviation_pct=5.
- HR.high=100, v=115 → warning, deviation_pct=15.
- HR.high=100, v=125 → critical, deviation_pct=25.
- HR.low=60, v=42 → critical (30% below).
- SpO2.low=90, v=70 → critical (22% below).
- SpO2.low=90, v=86 → info (~4% below).

### 4.2 Code blue at top tier
- `code.blue` scene alarm has severity="danger".
- code_blue_button (M29) severity="danger".
- Code-blue WAV unchanged — still `03_code_blue.wav`.

### 4.3 Tiered + concurrent audio
- `AUDIO_REPEAT_MS` table has all four keys with 2500/5000/15000/35000.
- `_audioCadenceTier` reads `a.severity` and routes "danger" to its own tier.
- 700 ms fast ticker exists with `_lastAlarmsForAudio` cache.
- Dispatcher creates one `new Audio(url)` per alarm + a CONCURRENTLY comment.

### 4.4 PIA cascade tightened
- `CASCADE_AUDIO_REPEAT_MS = 2500` (old `8000` constant removed).

### 4.5 Collapsible panel
- Section renders with class `ns-thresholds ns-collapsed` on first paint.
- Toggle element has id `ns-thresholds-toggle` with `aria-expanded="false"` + `aria-controls="ns-thresholds-form"`.
- Caret span present.
- JS has `wireThresholdToggle`, `ns-collapsed` class manipulation, Enter/Space keyboard handling.
- CSS hides the form when collapsed; caret rotates when expanded.

All 17 pass. Full v7 suite **441 passed, 1 skipped, 0 regressions** (was 424 pre-M54). Five pre-existing tests updated to reflect M54's intentional contract changes (code-blue severity, magnitude-based threshold severity, PIA cascade cadence).

---

## 5. Cadence math — why these numbers

Real bedside-monitor cadences are roughly:
- IEC 60601-1-8 high-priority alarms: 2.5–5 second repeat interval.
- Medium: 10–30 seconds.
- Low: ≥ 30 seconds.

M54 lands on:
- danger 2.5 s — operator wants code blue "with minimal time gap".
  2.5 s is the IEC lower bound and the shortest cadence that doesn't
  bury other concurrent alarms.
- high 5 s — at the spec's upper bound for high-priority audio.
- medium 15 s — middle of the IEC range.
- low 35 s — long enough to avoid ear fatigue for low-acuity alarms
  (a slipped call-bell shouldn't sound every 8 seconds).

For the magnitude→severity thresholds (10% / 20%), the operator's
phrasing is taken literally:
- 0–10% past bound = LOW
- 10–20% past bound = MEDIUM
- > 20% past bound = HIGH

This matches typical clinical practice: a small dip across the
boundary is a hint, a deep drop is an emergency.

---

## 6. Operator demo

1. Open the Nursing Station — the **Alarm thresholds** section is
   collapsed by default; click the header to expand. Click again to
   collapse. The caret rotates.
2. From a Per-Patient Console, set SpO2 = 88 (~2% below the 90
   default threshold). The Nursing Station alarm fires at **info**
   severity (greyed-out row) with a low chime every ~35 s.
3. Drop SpO2 to 80 — alarm escalates to **warning** (yellow), chime
   every ~15 s.
4. Drop SpO2 to 65 — alarm escalates to **critical** (red), chime
   every ~5 s.
5. Inject a `code.blue` scene from any encounter — top-row red
   alarm with **danger** severity; the chime now sounds every ~2.5 s,
   near-continuous.
6. With code blue still active, inject a second alarm (HR or
   SpO2). Both tones play simultaneously — code blue's repeating
   high-pri tone over the other tier's chime.
7. Silence the code blue — both stop. After 45 s the silence
   expires; if still active, audio resumes at the same cadence.

---

## 7. What was deliberately NOT changed

- **WAV library** — `_METRIC_FILES` and `_SPECIAL_FILES` are
  unchanged. `severity_to_priority` still maps `danger → high` so
  the WAV lookup keeps working with the existing assets. The new
  `danger` cadence tier is JS-side only.
- **Threshold-alarm sort order** — threshold alarms still use
  `ts=0` so they sort to the BOTTOM of their severity bucket. A
  critical-severity threshold breach sorts below a critical-severity
  device alarm with a real timestamp. M48 invariant preserved.
- **PIA flash animation** — gated by `_cascadeKey` (NEW alarm set
  triggers a restart), not by audio cadence. Don't want the CSS
  animation restarting every 2.5 s; the steady flash that runs while
  `pia-cascade-active` is sufficient.
- **No persistence** — collapsed/expanded state of the threshold
  panel is in-memory only. Reload resets to collapsed. If the
  operator wants the preference to persist, add a `localStorage`
  read/write in `wireThresholdToggle`.

---

**Closes:** all four M54 asks in full.
