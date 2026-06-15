# PLAN — FR-012 Advanced Clinical Devices (telemetry monitor · vent monitor · ventilator w/ controls)

**Date:** 2026-06-14
**Status:** PLAN AUTHORED — awaiting greenlight
**Author:** Claude Code build agent
**Companion reading:** `…/Physoligic engine control and integration/STANDALONE_INTEGRATION_PLAN.md`
(PhysioBridge, READ-ONLY), `…/Ventilator_Control_Build_Plan.md`, `vrai-faces/Memory_management.MD`,
`docs/PLAN-2026-06-13-gui-mission-control.md` (FR-011, resumability spine).

---

## 0. Summary

Add three new **advanced clinical devices** to the MedSim V8 device framework, surfaced under a new
**"Advanced devices"** group in the control-room *Simulated devices* picker:

1. **Telemetry monitor** — full-screen bedside patient monitor (HR/ECG, SpO₂/pleth, RR, NIBP, etCO₂),
   with the standard **nursing-station telemetry alarm set** (asystole, VF/VT, brady/tachy, desat,
   apnea, lead-off, …) that the instructor can arm and that auto-fire on threshold breach.
2. **Vent monitor** — a ventilator *display* surface (airway pressure/flow/volume scalars, P-V & F-V
   loops, vent numerics) with ventilator alarms.
3. **Ventilator with control interface** — the interactive vent: mode + settings with mode-aware ranges,
   set-vs-measured, maneuvers; **its control changes feed patient physiology** (and clear/raise alarms).

Plus the headline clinical feature:

4. **Ventilator fault injection** — a curated, bounded catalog of common real-world vent problems
   (air leak, circuit disconnect, secretions, bronchospasm, patient **bucking/coughing**, auto-PEEP,
   apnea, O₂-supply failure, …) the instructor injects into a running scenario. Each fault **impacts
   global patient physiology** *and* **triggers the matching equipment alarms** — same arm-and-catch
   teaching model as FR-008 staged medication errors.

---

## 1. The decisive architectural finding

A four-agent read of medsim_v8 (verified again 2026-06-14) establishes:

- **medsim_v8 has no physiology engine.** `portal/telemetry.py:1-34` and `portal/ecg.py` both state it in
  comments ("No physiological model … until a true physiology engine lands"). Vitals = the most recent
  `vitals.record` chart event + jitter + instructor overrides (`telemetry.snapshot()`); ECG = an
  11-rhythm static parametric catalog rendered client-side.
- **There is no ventilator anywhere**, and **no full-screen bedside monitor** (ECG/vitals show only in
  the instructor console + charge-nurse mini-strips).
- **The architecture is event-sourcing / fold.** Device + chart state are pure folds of append-only
  `device_event` / `chart_event` SQLite logs; the WebSocket layer is "advisory, not the system of
  record." Patient identity is `encounter_id` (= `session_id`).
- **PhysioBridge** (the project in `…/Physoligic engine control and integration/`) is a standalone
  physiologic engine (Kitware Pulse-based; currently runs on a deterministic **stub** — native PyPulse
  binding "not yet implemented") that already produces exactly the vitals/ECG/vent waveforms and the
  vent-coupling model we need. Its own `STANDALONE_INTEGRATION_PLAN.md` recommends a **hybrid**: a v8-side
  *pull shim* (Shape B) + **v8 device bundles** (Shape A) — and says the device bundles are a **v8-team
  task** because PhysioBridge must never edit the v8 tree.

### Decision (recommended): build v8-native, PhysioBridge-forward

We build the three devices as **first-class v8 device-framework surfaces** that read/write v8's existing
**event-log vitals contract** — NOT as a hard runtime dependency on PhysioBridge.

- **Why:** PhysioBridge's native engine is unfinished (stub only); taking a runtime dependency would block
  this feature on another project. v8's event log is the system of record and the right seam. This is
  precisely the "Shape-A device bundles, built by the v8 team" that PhysioBridge's plan calls for.
- **Physiology source of truth = the `vitals.record` event log**, read via `telemetry.snapshot()`. A thin
  v8-side **`physiology` module** (D2) reads that and lets devices write bounded deltas back
  (`vitals.record`, `surface="physiology"`), reusing the FR-008 impact precedent
  (`med_errors.py` already writes `vitals.record` with `surface="impact"`).
- **PhysioBridge drops in later (Shape B)** with zero device changes: a ~40-line shim pulls
  `GET /api/v8/vitals/{id}` each tick and appends the same `vitals.record` rows. The devices keep working;
  the numbers simply become real coupled physiology instead of bounded heuristics. We **port PhysioBridge's
  clinical models as the reference** (vent coupling FiO₂→SpO₂ / PEEP→recruit-then-overdistend /
  MV→EtCO₂ with condition ceilings; the abnormality drivers; the alarm taxonomy; the rhythm set) so the
  two systems stay vocabulary-compatible.

> Alternatives considered: (a) **hard-depend on PhysioBridge** — rejected, blocks on its unfinished
> engine; (b) **static/scene-only, no coupling** — rejected, the ventilator teaching loop requires that
> control changes and faults move vitals. Both remain reachable from this design if desired.

---

## 2. Where it plugs in (verified insertion points)

| Concern | File · anchor | Action |
|---|---|---|
| Device-kind registry | `portal/devices/registry.py:25` `KIND_DIRS` | + `telemetry_monitor`, `vent_monitor`, `ventilator` → new subdirs |
| Engine factory | `portal/devices/engine/state_machine.py:138` `make_engine()` | + branches for the 3 kinds |
| Device base engine | `portal/devices/engine/state_machine.py:34` `DeviceEngine` (initial_state/apply/tick/fold/handle/run_tick) | subclass per device |
| "Simulated devices" picker | `portal/templates/control_ops.html:740-800` (kind dropdown @768, model @772) | group into **Basic / Advanced** optgroups (the new pull-down) |
| Picker JS | `portal/static/control_ops_devices.js` (`loadModels`, `loadAlarmCatalog`) | category grouping; per-kind alarm catalog |
| Model list API | `portal/devices/routes.py:985` `GET /api/device/models` | auto-discovers new kinds (no change) |
| Register / join / bootstrap / WS | `routes.py:544` register · `:168` bootstrap · `devices/ws.py` `/ws/device/{id}` | generic — works for new kinds |
| Device page shell | `portal/templates/device_app.html` + `static/devices/device_app.js` | advanced devices need a richer renderer (waveforms) → new template/JS per surface |
| Vitals source of truth | `portal/telemetry.py` `snapshot()` / overrides | the read side of the D2 physiology module |
| Vitals write precedent | `portal/med_errors.py` writes `vitals.record surface="impact"` | the write side pattern for fault impact |
| Alarm bus | `portal/alarms.py` (4-tier) + `alarm_sounds.py` (WAVs) + `devices/engine/alarms.py` (IEC-60601 tones) | + telemetry/vent tones & severities |
| Scenes palette | `portal/scenes.py` `PALETTE` (`{kind,params}`) | + vent-fault scene kinds (arming path) |
| Resumability | `portal/session_state.py` (FR-011 G1) + module `snapshot()/restore()` | new device config/armed-fault/vent-settings join the blob |
| Debrief | `portal/debrief.py` | alarms raised / faults caught / vent titration arc |

---

## 3. The "Advanced devices" pull-down (UX)

The current picker has one flat `device_kind` `<select>`. We group it:

```
Device type ▾
 ┌ Basic devices ───────────────
 │  IV pump · Enteral pump · Cabinet · Patient alarm
 ├ Advanced devices ────────────   ← new optgroup
 │  Telemetry monitor
 │  Vent monitor
 │  Ventilator (with controls)
 └──────────────────────────────
```

Selecting an Advanced kind reveals its model + a kind-specific config strip (e.g. patient-condition
preset for the ventilator; alarm-limit defaults for the monitor). Everything else (model dropdown, label,
character/bed assignment, QR) is the existing generic flow.

---

## 4. Clinical catalog A — telemetry-monitor alarms (nursing-station standard)

IEC-60601-1-8 priority → color/tone. Auto-fire on threshold breach **and** instructor-armable. (Ranges
are defaults, per-device editable; reuse `clinical_ranges.json` where present.)

| Alarm | Trigger | Priority |
|---|---|---|
| **Asystole** | no QRS ≥ 4 s | HIGH (red) |
| **Ventricular fibrillation (VF)** | rhythm = vfib | HIGH (red) |
| **Ventricular tachycardia (VT)** | rhythm = vtach / HR > 150 wide | HIGH (red) |
| **Extreme brady** | HR < 40 | HIGH (red) |
| **Extreme tachy** | HR > 150 | HIGH (red) |
| **Desaturation (SpO₂ low)** | SpO₂ < 90 (HIGH < 85) | MED→HIGH |
| **Apnea / RR low** | RR < 6 or no breath ≥ 20 s | HIGH |
| Bradycardia | HR < 50 | MED (yellow) |
| Tachycardia | HR > 120 | MED |
| RR high | RR > 30 | MED |
| NIBP high / low | SBP >180 / <90 (or MAP <60) | MED |
| Frequent PVCs / couplet / R-on-T | ectopy count | LOW (cyan/advisory) |
| AFib / irregular | rhythm flag | LOW |
| **Lead off / artifact / "leads fail"** | technical | LOW (technical, distinct tone) |

Instructor controls (control room): set per-metric limits, **arm** an alarm to fire now or on next breach,
silence/acknowledge, and an **"alarm storm"** preset for triage drills (mirrors the charge-nurse use case).

---

## 5. Clinical catalog B — ventilator fault injection (the headline feature)

Bounded, structured injections (FR-008 model). Each fault declares: the **equipment alarm(s)** it raises,
the **waveform/numeric signature** the vent monitor shows, the **physiologic impact** (bounded vitals
deltas, condition-capped), **severity**, and the **resolution** that clears it. Instructor arms from the
control room; the fault can be immediate or scheduled to an encounter point.

| Fault | Alarm(s) raised | Vent signature | Physiologic impact | Resolution |
|---|---|---|---|---|
| **Air leak (cuff/circuit)** | Low Ppeak · Low Vt/MV · PEEP-not-maintained | exhaled Vt < set, PEEP droops, flow doesn't zero | gradual SpO₂↓, EtCO₂↓ (lost ventilation) | reseat/inflate cuff, fix circuit |
| **Circuit disconnect** | Low pressure (apnea-vent) · Low MV | flat P/flow, no breath | rapid SpO₂↓ | reconnect |
| **ET tube obstruction / kink / bite** | **High Ppeak** | Ppeak↑, Pplat normal-ish (↑resistance), flow scooped | SpO₂↓, EtCO₂↑ | suction / unkink / bite-block |
| **Secretions / mucus plug** | High Ppeak | sawtooth expiratory flow, Ppeak↑ | SpO₂↓, EtCO₂↑ | suction |
| **Bronchospasm** | High Ppeak | ↑resistance, prolonged expiration, ↑Ppeak-Pplat gap | SpO₂↓, EtCO₂↑, wheeze | bronchodilator |
| **Patient bucking / coughing (dyssynchrony)** | High Ppeak (transient) · possibly High RR | pressure spikes, flow reversal, missed triggers | transient SpO₂ dip, HR↑ | sedation/sync, mode/trigger adjust |
| **↓ Compliance (ARDS / edema / pneumothorax)** | High Ppeak/Pplat | Pplat↑, P-V loop flattens | SpO₂↓ (shunt), needs PEEP/FiO₂ | recruit / treat cause |
| **Auto-PEEP / air-trapping** | High Ppeak · (intrinsic PEEP) | expiratory flow doesn't return to 0 | ↓CO/BP, SpO₂↓ | ↑expiratory time, ↓RR, treat obstruction |
| **Apnea (sedation / central)** | **Apnea** → backup ventilation | no spontaneous trigger | EtCO₂↑, SpO₂↓ if backup off | backup mode / reduce sedation |
| **High RR / auto-trigger** | High RR · High MV | extra breaths, water-in-circuit oscillation | resp alkalosis (EtCO₂↓) | desensitize trigger, drain circuit |
| **O₂ supply failure / FiO₂ deviation** | Low/High FiO₂ · O₂-supply | FiO₂ off-target | SpO₂↓ | restore O₂ source |
| **Exhalation valve leak/fault** | circuit-integrity / low PEEP | PEEP not held | SpO₂↓ | service valve |
| **Vent inoperative / power-battery** | technical / power | screen fault | (backup bag) | power / swap vent |

> Impact is **bounded and condition-capped** (a sick lung can't be normalized by the vent alone), porting
> PhysioBridge `engine/vent_coupling.py` condition ceilings. Correct student action (suction, reconnect,
> titrate FiO₂/PEEP, sedate) drives vitals back toward baseline and clears the alarm.

---

## 6. Staged build (foundation-first; one device kind per stage; each gated)

Gate per stage: `.venv/bin/python -m pytest tests/v8 tests/test_device_routes.py -q` green + ruff clean;
commit + push; templates serve live, Python changes need a portal restart (now resume-safe via FR-011 G1).

- **D1 · Scaffold + "Advanced devices" pull-down.** Register the 3 kinds in `KIND_DIRS`; create
  `telemetry_monitors/ vent_monitors/ ventilators/` with minimal `spec.json` + placeholder `skin`/engine
  so each appears in the grouped picker, can be added, gets a QR, and opens a device page. Wire
  `make_engine()`. Group the picker into Basic/Advanced. *Accept:* models API lists new kinds; add→QR→join
  round-trips; resumability re-folds. **(safe foundation)**
- **D2 · Physiology module (the shared spine).** `portal/physiology.py`: `read(encounter_id)` (wraps
  `telemetry.snapshot()` + rhythm) and `apply_delta(encounter_id, deltas, *, surface, cause)` (appends a
  bounded `vitals.record`). Port PhysioBridge condition ceilings. This is the exact seam PhysioBridge Shape-B
  plugs into. *Accept:* delta writes a chart event; ceilings bound it; PHI-safe; resumable.
- **D3 · Telemetry monitor device.** Full-screen monitor surface (numerics + ECG/pleth/capno waveforms,
  reuse/extend `ecg_strip.js`); reads D2; nursing-station **alarm catalog §4** with auto-fire-on-threshold +
  instructor arm/silence; alarms ride the existing `alarms.py` bus + audio. *Accept:* renders live vitals;
  threshold breach raises the right alarm at the right priority; arm/silence; debrief logs alarms.
- **D4 · Vent monitor device.** Vent *display*: airway P/flow/V scalars + P-V/F-V loops + numerics
  (Ppeak/Pplat/Pmean/PEEP/Vt/RR/MV/I:E/Cdyn/FiO₂) + vent alarms; reads a vent-state contract. Port
  PhysioBridge `waveform/vent` synthesis (lumped R-C). *Accept:* waveforms/loops/numerics from settings;
  vent alarms fire.
- **D5 · Ventilator with controls.** Interactive vent: mode + settings with **mode-aware ranges**
  (port VC0 `control_settings`), set-vs-measured, maneuvers (insp/exp hold). **Controls feed D2** (port VC1
  coupling: FiO₂→SpO₂, PEEP→recruit/overdistend, MV→EtCO₂, condition ceilings) so titration moves vitals and
  clears/raises alarms. *Accept:* out-of-range rejected; mode hides/shows controls; FiO₂↑→SpO₂↑ to ceiling;
  over-PEEP penalty; change audited + resumable.
- **D6 · Ventilator fault injection (§5).** Curated fault catalog + arming engine + builder UI (FR-008
  pattern) + scenes-palette kinds; each fault → equipment alarm(s) + vent signature + bounded physiology
  impact (D2) + resolution; debrief "faults injected / caught / time-to-correct." *Accept:* each fault
  raises its alarm(s) + moves vitals within bounds; correct action clears it; armable to an encounter point;
  resumable.
- **D7 · Integration · resumability · field script · PhysioBridge-forward.** All three devices'
  config (alarm limits, vent settings, armed faults) join `session_state` snapshot/restore; field-test
  script; debrief polish; document the PhysioBridge Shape-B drop-in (`GET /api/v8/vitals/{id}` → the same
  `vitals.record` rows). *Accept:* restart resumes a live monitored/vented patient mid-fault; field script
  runs.

**Estimate:** ≈ D1 small · D2 small/med · D3 med · D4 med · D5 large · D6 large · D7 med.

---

## 7. Constraints & guardrails

- **PhysioBridge tree is READ-ONLY.** We only port concepts/values into v8; we never import from or write
  into that project.
- **PHI (ADR-0014):** device state + vitals deltas are structured numbers, never trainee free-text. Armed
  faults / alarm config are structured → safe to persist (FR-011 G1).
- **Local-first (ADR-0001):** all of this is portal-local; no new external dependency.
- **Honest constraint:** until PhysioBridge lands, physiology coupling is bounded clinical heuristics, not a
  full gas-exchange model — labeled as such (training representation), exactly as PhysioBridge labels its own
  stub/TV fidelity.
- **One module per PR**, each gated, consistent with the MedSim modular discipline.
- **Versioning (decided 2026-06-14):** physiology is built as **maturing v8 on the existing git repo**, NOT a `medsim_v9` folder fork (v1–v7 were pre-git snapshots; v8 is the first real repo). A `v9.0` git tag + `medsim8`→`medsim9` package bump is cut as a **release marker** only when physiology is real end-to-end (FR-012 complete + a working PhysioBridge Shape-B round-trip).
