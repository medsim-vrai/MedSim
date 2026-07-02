# FR-012 Field-Test Script — Advanced Clinical Devices

**Scope:** telemetry monitor, vent monitor, ventilator (controls + faults), and
the instructor state/waveform selection. Run on real tablets against a live
portal. Mark each step ✅/❌; paste failures back to Claude Code with the step #.

**Companion:** `docs/PLAN-2026-06-14-advanced-devices.md` (stages D1–D7),
`DESIGN-2026-06-14-physiology-source-authority.md`.

---

## 0. Setup

| # | Step | Pass |
|---|---|---|
| 0.1 | Restart the portal on current code: `pkill -TERM -f run_portal.py` then `MEDSIM_NO_BROWSER=1 MEDSIM_HOST=0.0.0.0 .venv/bin/python run_portal.py`. Watch for `[resume] restored last session …` if one was active. | ☐ |
| 0.2 | Log in to the control room (vault). A prior scenario auto-resumes; otherwise configure one (single- or multi-patient). | ☐ |
| 0.3 | On each tablet: open `http://<lan>:8761`, install the CA (Android: Settings → Security → Install a certificate → CA). Reopen the `https://…:8760` device URL — trusted, no warning. | ☐ |
| 0.4 | Control room → **Add device → Device type ▾ → Advanced devices**. Confirm the group lists **Telemetry monitor · Vent monitor · Ventilator**. | ☐ |

## 1. Telemetry monitor

| # | Step | Pass |
|---|---|---|
| 1.1 | Add a **Telemetry monitor**, mint the QR, open it on a tablet. Tap once → it goes **full screen** (no browser header) + audio enabled. | ☐ |
| 1.2 | Live numerics + scrolling **ECG / pleth / resp** render; the QRS peak is **steady** (no flicker). No "PROGRAM PUMP" box. | ☐ |
| 1.3 | Per-patient console → **ECG strip → Waveform** → pick **Sinus tachycardia**. Monitor HR rises to ~120, ECG speeds up; the **Nursing Station** mini-strip shows the same. | ☐ |
| 1.4 | Pick **VF** (or **Asystole**): ECG goes chaotic/flat, **HR 0, BP 0, SpO₂ crashes**, alarm sounds on the monitor + the **nursing-station board** (critical/danger). | ☐ |
| 1.5 | Tap **Silence** on the monitor → audio mutes (visual stays). Pick **Normal sinus** → vitals + waveform recover. | ☐ |
| 1.6 | Device card → **Detail / inject** → fire a tone (e.g. *leads off*) → device flashes + sounds; **Clear**. | ☐ |

## 2. Ventilator (controls + state)

| # | Step | Pass |
|---|---|---|
| 2.1 | Add a **Ventilator**, open on a tablet. The control screen shows mode buttons, **−/+ steppers**, set-vs-measured numerics, maneuvers; waveforms fill the upper area, **controls below**. | ☐ |
| 2.2 | Raise **FiO₂** / **PEEP** with the steppers → the **telemetry monitor's SpO₂ rises** (toward the condition ceiling). Over-PEEP (>16) → SpO₂ dips (overdistension). | ☐ |
| 2.3 | Console → **Ventilator state** → pick **ARDS — lung-protective**. Vent settings switch to PC-CMV / PEEP 12 / FiO₂ 0.70; the patient's SpO₂ settles lower (shunt); waveforms reshape. | ☐ |
| 2.4 | Maneuvers: **Insp hold** → Pplateau toast; **Exp hold** → auto-PEEP estimate; **100% O₂** → FiO₂ jumps to 100%. | ☐ |

## 3. Ventilator fault injection

For each fault: control room → ventilator card → **Detail / inject → Ventilator fault → pick → Arm**.

| # | Fault | Expect on the vent monitor + patient | Pass |
|---|---|---|---|
| 3.1 | Air leak | low Vt / low MV alarm; **measured Vt < set Vt** (set-vs-measured diverges); SpO₂ drifts down. | ☐ |
| 3.2 | Circuit disconnect | low-pressure / low-MV alarm; rapid SpO₂ crash. | ☐ |
| 3.3 | ET obstruction | **high-pressure** alarm (Ppeak > 35); SpO₂ down, EtCO₂ up. | ☐ |
| 3.4 | Patient bucking | high-pressure spikes; **HR jumps**. | ☐ |
| 3.5 | Auto-PEEP | auto-PEEP alarm; BP dips. | ☐ |
| 3.6 | Apnea | apnea alarm; EtCO₂ climbs. | ☐ |
| 3.7 | For any fault: read the **resolution** text, perform it (or **Clear**) → alarm clears, patient recovers via the coupling. | ☐ |

## 4. Resumability + debrief

| # | Step | Pass |
|---|---|---|
| 4.1 | With a monitor + ventilator live (and a fault armed), **gracefully restart** the portal (`pkill -TERM`). On boot: `[resume] restored last session …`. Re-login; the scenario, vent settings, condition, and armed fault are intact. | ☐ |
| 4.2 | Reopen the device pages (re-scan QR) — they resume showing the current physiology. | ☐ |
| 4.3 | End the scenario → open the debrief → the **alarm log** lists the monitor/vent alarms that fired (tone + raised/cleared). | ☐ |

---

### Notes for paste-back
When a step fails, paste: the **step #**, what you saw vs expected, the **device build** (console: `[MEDSIM device] booting build vX.Y.Z`), and any console/`/tmp/medsim_portal.log` error. Claude fixes against the step.
