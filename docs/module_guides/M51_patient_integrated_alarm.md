# M51 — Patient Integrated Alarm (PIA) device

**Phase:** Phase 7 follow-on (post-M50, operator feedback)
**Status:** **DONE**
**Blocked by:** M25 (Per-Patient Console), M26 (alarm bus), M27 (Nursing Station), M49 (alarm sounds), M50 (code blue cascade)
**Blocks:** none
**Estimated effort:** 1 day

---

## 1. Purpose

A new device that bedside students hold (or sits on a tray within
reach of the simulated patient) to issue four common emergency-room
requests on a single tablet screen:

> "Create a new device to add to the device list, the 'Patient
> integrated alarm' for encounters – three functions- call bell,
> bed alarm, code blue and intercom with nurses station on one
> table. The instructor needs to able to trigger events as well as
> students responding to clear alarms or to use the intercom or
> activate the Code Blue alarm. The code blue should also cause
> the other Patient integrated alarm state the location-in this
> case encounter as well as on the nurse station and instructor
> control areas. Use available sound files to support the various
> alarms. The screen on the device should flash with alternating
> colors to indicate the alarm or if a function like intercom is
> active."

The PIA replaces four separate M29 future-device stubs (call_bell,
bed_alarm, code_blue_button, fire_alarm — minus fire) with a single
real device a student can register from the encounter console, hand
to the patient role-player, and use throughout the simulation.

**Why one device with four buttons instead of four devices?** Because
in a hospital room a patient has exactly one tablet at the bedside.
Combining the buttons keeps the bedside UX honest, simplifies QR
provisioning (one scan per bed, not four), and gives every PIA the
same room-wide awareness — when a code is called anywhere in the
room, *every* PIA screen turns red.

---

## 2. What ships

### 2.1 New device kind

`patient_integrated_alarm` joins the registry's `KIND_DIRS` map and
its `pia_v1` model lives under `portal/devices/pia/pia_v1/`. The
model directory is a stub by design — `spec.json` declares four
controls and the three alarm tones the device knows how to play,
and `skin.svg` is a placeholder kept only so the registry's
`load_spec` / `load_skin` calls don't fail for legacy callers. The
PIA renders a **dedicated `device_pia.html` template**, not the
vendor-skin overlay used for pumps/cabinets, because the PIA is a
control surface (4 big buttons + flashing canvas), not a
vendor-hardware mock.

### 2.2 Device-side UI — `device_pia.html` + `pia_app.js` + `pia_app.css`

Layout:

```
┌──────────────────────────────────────────────────────┐
│ Patient Integrated Alarm · Bed 1          ● Connected│
├──────────────────────────────────────────────────────┤
│ [🚨 CODE BLUE — Bed 2]    ← cascade banner (hidden   │
│                              unless a code is active │
│                              ANYWHERE in this room)  │
├──────────────────────────────────────────────────────┤
│  ┌──────────────┐   ┌──────────────┐                 │
│  │ 🔔 Call Bell │   │ 🛏 Bed Alarm │                 │
│  │ Summon staff │   │ Patient out  │                 │
│  └──────────────┘   └──────────────┘                 │
│  ┌──────────────┐   ┌──────────────┐                 │
│  │ 🚨 Code Blue │   │ 🎙 Intercom │                  │
│  │ Cardiac/resp │   │ Page nurses  │                 │
│  └──────────────┘   └──────────────┘                 │
└──────────────────────────────────────────────────────┘
```

Each press hits `POST /api/device/{station_id}/event` with
`type="pia.button"` + `payload={action, by}`. The Code Blue button
gates on a `confirm()` to prevent fat-finger fires.

On press, the device:
1. POSTs the event.
2. Plays a one-shot WAV (from the M49 clinical-alarms library).
3. Flashes the entire screen frame in an alternating colour
   matched to the kind (blue for call_bell, amber for bed_alarm,
   red for code_blue, green for intercom).
4. The footer's "last event" stamp updates so the student knows
   the press registered even before any audio plays.

### 2.3 Server-side button router — `_handle_pia_button`

In `portal/devices/routes.py` the `api_device_event` route detects
PIA button events and dispatches:

| action              | Effect                                                           |
|---------------------|------------------------------------------------------------------|
| `call_bell`         | `alarm.injected` device_event with `tone=call_bell` → alarm bus picks it up at `severity=info` |
| `bed_alarm`         | `alarm.injected` device_event with `tone=bed_alarm` → alarm bus picks it up at `severity=warning` |
| `code_blue`         | `scenes.apply(code.blue)` — the existing M7 scene — which writes chart events + raises a room-wide code-blue alarm |
| `intercom_request`  | `comm.intercom_request` chart event + transcript line ("🎙 Intercom requested") |

This re-uses the existing M26/M27 plumbing — the PIA does **not**
introduce a new alarm bus channel; it just emits the same kinds of
events the Nursing Station's "inject alarm" buttons emit, so the
existing alarm board / silence / clear flows work unchanged.

### 2.4 Room-wide code-blue cascade

When any PIA fires a Code Blue, the scene apply writes a `code.blue`
alarm into the room's alarm bus. Every PIA in the room polls
`/api/room/alarms` every 3 s (`pollCascade` in `pia_app.js`).

If ANY code-blue alarm is active anywhere in the room, every PIA:
- Shows the **🚨 CODE BLUE — Bed N** cascade banner across the top,
  reading the originating encounter's label so the bedside student
  knows WHERE the code is, even though THEIR bed is calm.
- Adds the `pia-cascade-active` class to the frame, which keeps the
  red flash continuous until the alarm clears.
- Plays the `03_code_blue.wav` once, ONLY when the active set
  changes (`_cascadeKey` dedupes by sorted alarm_ids).

This satisfies the operator ask: *"the code blue should also cause
the other Patient integrated alarm state the location"*. Same
mechanism notifies the Nursing Station (via the alarm bus already
displayed there) and the instructor's encounter console (via the
M27 alarm card).

### 2.5 Instructor mirror panel

When a PIA station is bound to an encounter, the encounter
console's Devices card renders a four-button mirror panel inline
(`📟 Instructor mirror — fire any event on this bed's PIA tablet`).
Each button POSTs the same `pia.button` event so the instructor can
trigger any of the four actions without leaving the encounter view
— essential for "scripted" calls in pre-planned drills, or for
firing the alarm if the patient role-player isn't reachable.

---

## 3. Files touched

### New files
- `portal/devices/pia/pia_v1/spec.json` — declares 4 controls + 3 alarm tones.
- `portal/devices/pia/pia_v1/skin.svg` — registry-stub SVG (PIA renders a custom template).
- `portal/templates/device_pia.html` — 4-button + cascade banner tablet UI.
- `portal/static/pia_app.js` — press handler, sound playback, screen flash, cascade poller, heartbeat.
- `portal/static/pia_app.css` — dark theme + per-kind flash keyframes.
- `tests/v7/test_patient_integrated_alarm.py` — 13 acceptance tests.
- `docs/module_guides/M51_patient_integrated_alarm.md` — this guide.

### Modified
- `portal/devices/registry.py` — `patient_integrated_alarm` added to `KIND_DIRS` and `REFERENCE_MODELS`.
- `portal/devices/engine/state_machine.py` — `make_engine` branches to a thin `PiaEngine` (no custom reducer; the base no-op reducer is enough because PIA effects are side-effects routed in `routes._handle_pia_button`, not folded into device-station state).
- `portal/devices/routes.py` — `device_app` branches to `device_pia.html` for PIA kind; `api_device_event` calls `_handle_pia_button` for `pia.button` events.
- `portal/static/encounter_console.js` — `📟 Patient Integrated Alarm` kind label, PIA mirror-panel render in the device card, `pia` dispatch branch in `onDeviceAction`.
- `portal/static/encounter_console.css` — `.device-card-pia` + `.pia-mirror-row` + `.pia-mirror-btn` styles.

---

## 4. Acceptance — what M51 must satisfy

Source: `tests/v7/test_patient_integrated_alarm.py` (13 tests).

1. **Registry**
   - `patient_integrated_alarm` appears in `registry.list_kinds()`.
   - `registry.available_models("patient_integrated_alarm") == ["pia_v1"]`.
   - The spec declares `call_bell`, `bed_alarm`, `code_blue`, and `intercom` controls.

2. **Engine factory**
   - `make_engine(kind="patient_integrated_alarm", model="pia_v1")` returns a `PiaEngine` without raising.

3. **Device template**
   - `GET /device/{join_code}/{station_id}` for a PIA station serves `device_pia.html` (carries `pia-frame`, `pia-grid`, all four `data-action` buttons, loads `pia_app.js`).
   - Does NOT serve the generic vendor-skin template.

4. **Button routing**
   - `call_bell` press → `alarm.injected` device alarm on `/api/room/alarms` with `kind="call_bell"`, `source="device"`, correct `encounter_id`.
   - `bed_alarm` press → same shape, `kind="bed_alarm"`.
   - `code_blue` press from a 2-bed room → code-blue alarm visible on `/api/room/alarms` with `encounter_label` populated (so other PIAs can show *where* the code is), severity ≥ critical.
   - `intercom_request` press → `comm.intercom_request` chart event written with the station_id; transcript carries a "🎙 Intercom requested" line in the last 4 entries.
   - Unknown action → route still returns 200 (event persisted by engine), no alarm raised.

5. **Sound assets**
   - `01_bed_exit_alarm.wav`, `02_call_bell.wav`, `03_code_blue.wav` all exist on disk under `portal/static/sounds/clinical_alarms/`.
   - `pia_app.js` references all three by filename + carries all four `pia-flash-*` class names + cascade poller hits `/api/room/alarms`.

6. **Encounter console**
   - `encounter_console.js` contains the `patient_integrated_alarm` kind label.
   - Contains four `data-pia-action="…"` mirror buttons and a `pia.button` POST handler.

7. **CSS**
   - All four `@keyframes flash-*` rules defined plus `cascade-pulse` for the banner.
   - `.pia-frame.pia-flash-code-blue` and `.pia-cascade-active` rules present.

All 13 tests pass in `pytest tests/v7/test_patient_integrated_alarm.py` and the full v7 suite (387 passed, 1 skipped) shows no regression.

---

## 5. Operator demo script

1. From `/portal/control/ops` for an active multi-patient room, open
   any encounter. The Devices card shows the existing inline device
   manager.
2. Click **Add device**, pick **Patient Integrated Alarm → pia_v1**,
   give it a label (e.g. "Bed 1 PIA"). A QR code appears in the
   Devices card.
3. Scan the QR with a tablet — the tablet loads `device_pia.html`
   showing the four buttons + cascade banner area.
4. From a second encounter, repeat steps 2–3 with another tablet
   (or browser window simulating one).
5. **Test the four buttons** from the bedside tablet:
   - 🔔 Call Bell — screen flashes blue, soft chime plays, the
     Nursing Station's alarm board picks up a `call_bell` alarm
     scoped to this bed.
   - 🛏 Bed Alarm — screen flashes amber, bed-exit chime plays,
     Nursing Station picks up `bed_alarm`.
   - 🚨 Code Blue — confirm dialog appears, then screen flashes
     red, code-blue tone plays, **every other PIA in the room also
     flashes red and shows "CODE BLUE — Bed N"**. The Nursing
     Station's code-blue alarm + the encounter's alarm card both
     fire.
   - 🎙 Intercom — screen flashes green, the transcript on the
     encounter console shows "🎙 Intercom requested", and the
     Nursing Station's intercom UI surfaces the request.
6. From the instructor's encounter console, use the **📟
   Instructor mirror** buttons in the Devices card to fire any of
   the four actions without touching the tablet — useful for
   scripted drills.

---

## 6. Things the PIA deliberately does NOT do

- **No microphone capture or 2-way audio.** Intercom uses the
  existing M28 nurse→bedside one-way voice channel; the PIA just
  signals "patient wants the intercom open" via a chart event. The
  Nursing Station student or instructor opens the audio leg.
- **No alarm silence / clear from the device side.** Those are
  operator + nurse-station actions. The PIA is a *patient-facing*
  device — silencing your own emergency alarm would defeat the
  point.
- **No fire-alarm button.** The M29 stub still exists for the
  fire-alarm case (it's a building-level event, not a per-bed
  device). PIA stays focused on bedside-only actions.
- **No persistent screen lock or kiosk-mode enforcement.** Kiosk
  mode is a deployment concern (iOS Guided Access, Android pin-
  to-app) — the device-side code just hides browser chrome via the
  meta tags `apple-mobile-web-app-capable` + `theme-color`.

---

## 7. Future hooks

- **PIA assignment to a Student.role.** Right now a PIA is bound
  to an encounter, not a student. A future cleanup could let the
  patient role-player register against the PIA so transcript
  entries carry their student_id.
- **Customizable alarm tones per encounter.** The 3 tones are
  hard-coded to M49 WAVs. Curriculum authors could pick alternate
  tones in the wizard.
- **Patient-side accept/decline of the intercom open.** Right now
  the request fires once; the Nursing Station controls when to
  open audio. A future module could add a "Nurse is opening
  intercom" notification on the PIA with an accept/decline
  affordance.

---

**Closes:** the operator's M51 ask in full. No follow-on tickets
identified.
