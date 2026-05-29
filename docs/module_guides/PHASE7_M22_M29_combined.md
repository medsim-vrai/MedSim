# Phase 7 — Nursing Station + Supervisor Telemetry/ECG/Intercom (M22–M29)

**Status:** 🟢 **PHASE 7 COMPLETE** (2026-05-26)
**Combined guide** — eight modules + five 1.x touch-ups shipped in
one autonomous pass. Each section below maps to one module from the
Phase 7 plan.

---

## Pre-Phase 7 touch-ups (1.1–1.5)

| # | What | Files |
|---|---|---|
| 1.1 | "Charge-nurse dashboard" → "Multi-Patient Control" rename (label-only) | `templates/control_room.html`, `templates/base.html` |
| 1.2 | `Student.role` field + schema migration v5 (`student.role` default `'bedside'`) + `students_by_role` helper | `ehr_db.py`, `control_room.py` |
| 1.3 | M5 dashboard card click now routes to `/portal/room/encounter/{id}` (M22 target) | `static/control_room.js` |
| 1.4 | M7 alarm-class scenes (`code.blue`, `pump.alarm`) tag payloads with `level='alarm'` so the M26 bus picks them up | `scenes.py` |
| 1.5 | `devices.registry.list_kinds()` helper | `devices/registry.py` |

Two M1 tests updated to be future-proof (`schema_version >= 4`
instead of `== 4`).

---

## M22 — Per-Patient Console scaffold

**Goal:** instructor drill-in at `/portal/room/encounter/{id}` —
new template + JS + CSS scaffold with 6 cards (telemetry, ECG,
device list, telemetry overrides, scene injector, recent chart
events). M22 ships the scaffold; M23/M24/M25 light up each card.

**Files:** `templates/encounter_console.html`,
`static/encounter_console.{js,css}`, `server.py` route. **4 tests
pass** (route renders, 404s on unknown id, 404s when no active
room, clone indicator surfaces).

---

## M23 — Telemetry simulation engine

**Goal:** derive a continuous HR/BP/SpO2/RR/Temp snapshot per
encounter from the latest `vitals.record` event + small jitter,
with operator force-set overrides per metric.

**Files:** `portal/telemetry.py` (new), routes added to `server.py`
(`GET /api/encounter/{id}/telemetry` + `POST
/api/encounter/{id}/telemetry/override`). Overrides live in-memory
on the `Encounter.telemetry_overrides` dict (the room dies with the
server; no restart-survival needed). **5 tests pass** (snapshot from
latest vitals, defaults fallback, scene injection shifts snapshot,
overrides take precedence, route round-trip set/clear/clear_all).

---

## M24 — ECG waveform library

**Goal:** static catalog of 11 cardiac rhythms (NSR, sinus tachy/
brady, AFib, AFlutter, monomorphic VT, polymorphic VT/torsades,
VFib, asystole, PEA, paced). Per-encounter `ecg_rhythm_id` +
`ecg_enabled` toggle. Client-side SVG renderer scrolls a 6-second
strip.

**Files:** `portal/ecg.py` (new) + `static/ecg_strip.js` (new
client renderer). Routes: `GET /api/ecg/catalog`,
`GET /api/encounter/{id}/ecg`, `POST /api/encounter/{id}/ecg`.
**8 tests pass** (catalog has 11 with required fields, get/lookup
helpers, encounter defaults, route round-trip, unknown-id rejected,
observer can't mutate).

---

## M25 — Per-Patient Console rich features

**Goal:** light up M22's scaffold with live telemetry poll (1s),
ECG strip via `ecg_strip.js` + picker dropdown, device list from
`/api/room/state`, telemetry override sliders (one per metric),
override-aware coloring. Scene injector preserved from M22.

**Files:** rewritten `static/encounter_console.js` + template
includes `ecg_strip.js`. **2 tests pass** (template references
renderer + the right anchors; end-to-end telemetry route round-trip).

---

## M26 — Alarm bus

**Goal:** unified active-alarm list aggregating three sources —
device-event `alarm.injected` (v6 pump/cabinet), chart-event
`level='alarm'` payloads (M7 + Phase 7 1.4), and future-device
button presses (M29). Each alarm carries `severity`
(`info`/`warning`/`critical`), `source`, `kind`, `encounter_id`,
`alarm_id` (deterministic, stable across reads).

**Files:** `portal/alarms.py` (new), routes `GET /api/room/alarms`
+ `POST /api/alarm/{id}/clear`. **6 tests pass** (pump device
alarm surfaces, code.blue scene alarm surfaces, clear removes from
list, critical-first ordering, unknown id 404, no-room 404).

---

## M27 — Nursing Station student role

**Goal:** new in-sim role — supervisor monitors every bed remotely.
Student-join page (M9) gains a role-picker step (Bedside vs Nursing
Station). Nurse_station register skips encounter assignment + chat
station creation; the student lands on
`/portal/students/nurse_station?sid=...` with one bed card per
encounter (mini telemetry strip + mini ECG + device pills + alarm
board at top).

**Files:** new `templates/nurse_station.html`,
`static/nurse_station.{js,css}`, role-picker step in
`templates/student_join.html`, role branching in
`static/student_join.js`, new `POST /portal/students/register_nurse`
+ `GET /portal/students/nurse_station` routes. **7 tests pass**.

---

## M28 — Intercom (one-way nurse → bedside)

**Goal:** nurse-station types a message → server writes a
`comm.intercom` chart_event with text + voice_id + persona_id (staff
persona auto-picked from encounter's `selected_personas` when
available); WS push (M16) on
`/ws/room/{room_code}` so the bedside chat station can play/show
it. Bedside replies via existing v6 chat path (text).

**Files:** `portal/intercom.py` (new), `POST
/api/intercom/{encounter_id}/page` route. Future-WebRTC upgrade
preserves the data contract. **7 tests pass** (comm event recorded,
staff voice when bound, no-voice fallback, route auth — 403 if
from_student_id is bedside, 400 on empty text, 404 on unknown
encounter, WS push fires).

---

## M29 — Future-device stubs

**Goal:** four new in-sim device kinds — `call_bell`, `bed_alarm`,
`code_blue_button`, `fire_alarm`. Each is a single-button bedside
press that emits an `alarm.injected` device_event with `tone=kind`.
M26's severity table classifies them appropriately (call_bell →
info, bed_alarm → warning, code_blue_button + fire_alarm →
critical).

**Files:** `portal/future_devices.py` (new), routes
`GET /api/future_devices/kinds` + `POST
/api/encounter/{id}/future_device/{kind}/press`. **9 tests pass**
(four kinds listed, each kind raises the right severity, unknown
kind 400, unknown encounter 404, no-room 404, WS push fires).

---

## Combined test summary

| Module | New v7 tests |
|--------|---:|
| 1.1–1.5 touch-ups (no new tests; updated 2 M1 brittle assertions) | 0 |
| M22 | 4 |
| M23 | 5 |
| M24 | 8 |
| M25 | 2 |
| M26 | 6 |
| M27 | 7 |
| M28 | 7 |
| M29 | 9 |
| **Total Phase 7** | **48** |

**v7 suite at start of Phase 7:** 132.
**v7 suite after Phase 7:** **180 passed, 1 Playwright skip**.
**Full v6 regression on v7:** **291 passed, 6 env-flaky, 2 skipped,
0 v7 regressions** (matches v6 baseline).

---

## Architecture overview after Phase 7

```
INSTRUCTOR (Operator) — /portal/room and children
├── /portal/control          (wizard — Single Patient / Room of N)
├── /portal/room              (Multi-Patient Control — was "Charge-nurse")
│   ├── encounter grid + Freeze/Resume/Scene/End controls
│   └── card-click → /portal/room/encounter/{id}
└── /portal/room/encounter/{id}  (Per-Patient Console — NEW M22+M25)
    ├── live telemetry strip       (M23)
    ├── ECG strip + picker         (M24)
    ├── device list                (M1.5 + M25)
    ├── telemetry overrides        (M23)
    ├── pre-targeted scene inject  (M7)
    └── recent chart events

STUDENT (in-simulation roles)
├── Bedside (existing M9)
│   ├── chat station            (v3)
│   ├── EHR station             (v5)
│   └── device station          (v6 pumps/cabinets)
│       + Phase 7 M29 stubs:
│           call_bell, bed_alarm,
│           code_blue_button, fire_alarm
└── /portal/students/nurse_station  (NEW M27)
    ├── multi-patient telemetry mini-strips  (M23)
    ├── mini ECG per bed                      (M24)
    ├── device pills per bed
    ├── alarm board                           (M26)
    └── intercom → any bed                    (M28)
```

---

## What still needs the operator

1. **LAN_TEST_V7.md sign-off** (still M21's open item) — now also
   covers Phase 7 surfaces.
2. **JS subscriber wiring on bedside chat station** for M28
   intercom audio playback. The server-side contract + WS push are
   live; the bedside JS hook (~15 lines in `station_chat.js`) is
   the only remaining wiring.
3. **v7.1 WebRTC upgrade for M28 intercom** — two-way mic-to-mic.
   Data contract is forward-compatible.

---

## Combined change list

| Date | Module | Files |
|------|--------|-------|
| 2026-05-26 | 1.1 rename | `templates/control_room.html`, `templates/base.html` |
| 2026-05-26 | 1.2 Student.role + schema v5 | `ehr_db.py`, `control_room.py` |
| 2026-05-26 | 1.3 drill-in route swap | `static/control_room.js` |
| 2026-05-26 | 1.4 scene alarm level tag | `scenes.py` |
| 2026-05-26 | 1.5 device kinds API | `devices/registry.py` |
| 2026-05-26 | M22 | `templates/encounter_console.html`, `static/encounter_console.{js,css}`, `server.py` route |
| 2026-05-26 | M23 | `portal/telemetry.py` (new), `server.py` routes, `control_session.py` field |
| 2026-05-26 | M24 | `portal/ecg.py` (new), `static/ecg_strip.js` (new), `server.py` routes, `control_session.py` fields |
| 2026-05-26 | M25 | rewritten `static/encounter_console.js`, template includes |
| 2026-05-26 | M26 | `portal/alarms.py` (new), `server.py` routes |
| 2026-05-26 | M27 | `templates/nurse_station.html`, `static/nurse_station.{js,css}`, role step in `student_join.html`, role branch in `student_join.js`, `server.py` routes |
| 2026-05-26 | M28 | `portal/intercom.py` (new), `server.py` route + WS push |
| 2026-05-26 | M29 | `portal/future_devices.py` (new), `server.py` routes + WS push |

## Open follow-ups

- Bedside chat station JS intercom playback hook (~15 lines).
- WebRTC v7.1 upgrade for two-way intercom audio.
- LAN_TEST_V7.md operator sign-off (now covers Phase 7 surfaces).
- The two voices test fixtures + four device_debrief tests (the
  pre-existing v6 env-flaky 6) — independent hygiene pass.
