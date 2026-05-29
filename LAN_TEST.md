# Medsim_v6 LAN acceptance test

The Phase 4 plans for both the pump device modules and the Pyxis cabinet
gate progression on a **multi-device LAN test on real tablets over wifi
with instructor fault injection.** This is that protocol.

Run it once after every behaviour-affecting change.

## What you need

- 1 laptop (instructor) — Chrome / Safari
- 2 tablets (students) on the same wifi as the laptop — iPad and/or Android tablet
- All three on the same LAN subnet (no client isolation on the wifi AP)
- A volume on the tablets so you can hear alarm tones

## Set-up

```bash
cd "/Users/petermarotta/Documents/Claude/Projects/Scenario structure to support character engagement/medsim_v6"
MEDSIM_HOST=0.0.0.0 ./.venv/bin/python run_portal.py
```

Note the **LAN URL** printed at startup (e.g. `http://192.168.1.42:8765`).

On the instructor laptop:

1. Open `http://127.0.0.1:8765`, log in.
2. Pick **New scenario** → choose 1 persona (e.g. P-001 Mr. Johnson) → Launch.
3. The control wizard hands you off to **/portal/control/ops**.

## Test 1 — A2HS install on iOS Safari

1. On iPad, open `http://<lan-ip>:8765/portal/control/ops`.
   *(Or skip ahead to the device QR — same A2HS hint shows there.)*
2. Verify the **Add to Home Screen** banner appears at the bottom of the
   landing page.
3. Tap Share → Add to Home Screen. Confirm the icon lands on the home
   screen with the MEDSIM glyph and label "MEDSIM Device".
4. Tap the home-screen icon — it should reopen in standalone mode (no
   Safari chrome). The same A2HS banner does NOT reappear (localStorage
   dismissal works).

**Pass:** icon present after closing Safari, reopens without browser chrome.

## Test 2 — Mint a pump + scan QR

On the instructor laptop, in the **Simulated devices** card:

1. Click **+ Add device (mint QR)**.
2. Pick `IV pump` → `BD Alaris` → label `"Bed 3 IV"` → assign to `P-001
   Mr. Johnson` → Mint.
3. A QR code appears in the modal. On the iPad's camera, scan it.
4. iPad opens the device join landing. Confirm it shows
   "BD Alaris · Bed 3 IV · assigned to P-001 Mr. Johnson".
5. Tap "Tap to load device →". The Alaris SVG renders within 2-3 seconds.
6. The TRAINING SIMULATION badge is visible at the bottom of the chassis.

**Pass:** SVG renders; instructor's roster card flips its dot to green.

## Test 3 — Instructor alarm injection latency

1. Instructor: click the Bed 3 IV card → **Detail / inject**.
2. Pick `air_in_line` from the alarm dropdown → **⚠️ Fire**.
3. Within **< 1 second** the iPad:
   - Plays the air-in-line tone (looping)
   - Pulses the chassis red
4. On iPad, tap the `key-silence` element on the SVG. Audio stops.
5. Tap the alarm indicator again to clear. The chassis stops pulsing.
6. In the operator's detail panel, the **Recent events** tail shows
   `alarm.injected → alarm.silenced → alarm.cleared`.

**Pass:** < 1s alarm latency over WebSocket; full silence/clear cycle
records in the event log.

## Test 4 — Pyxis cabinet workflow

1. Instructor: mint a `Dispensing cabinet` / `BD Pyxis MedStation`,
   label `"Cart A"`, assign to `P-001`.
2. On the second tablet (Android), scan the QR.
3. After the join landing, the Pyxis screen renders. Tap `btn-login` —
   the cabinet enters the menu screen.
4. Tap `btn-remove` → tap a med row → on a real Pyxis you'd scan the
   bottle; in sim, tap `btn-accept` to simulate scan-match.
5. Confirm `cabinet.scan_verify result=match` arrives in the instructor's
   detail panel.

**Pass:** the full login → patient → verb → med → scan → remove flow logs
correctly in the operator's tail.

## Test 5 — Character reassignment preserves history

1. Instructor: on the Bed 3 IV card → Detail → change assignment to a
   different persona → Reassign.
2. Verify the iPad's patient strip refreshes WITHOUT reload.
3. Open the debrief preview (📊 Preview debrief). The pump's
   `assignment_history` should show both characters with timestamps;
   prior `pump.*` events still carry the original character_id in their
   payload (look in `device_timeline`).

**Pass:** debrief shows two-row assignment history; old events still
attributed to the first persona.

## Test 6 — Pause / resume

1. Instructor: inject `low_battery` on the Alaris.
2. Confirm the tone loops on the iPad.
3. Click the **Pause** button at the bottom of `/portal/control/ops`.
4. Within < 1s on the iPad:
   - The looping audio stops
   - A red "SCENARIO PAUSED" banner appears
   - Tapping any control on the SVG does NOT fire — the banner flashes
5. Click **Resume**. The looping audio resumes. Tapping works again.
6. The active alarm is still in the state — no events were lost.

**Pass:** audio mutes on pause, resumes on resume; input gated; state
intact.

## Test 7 — End scenario → debrief

1. Click **✓ End scenario**.
2. iPad and tablet both show "SCENARIO ENDED" banner. Audio stops.
3. Instructor lands on the debrief page.
4. Open the debrief JSON — verify it contains:
   - `devices` (array, ≥ 2 entries)
   - `device_timeline` (sorted by ts, merging all events)
   - `alarm_log` (with `time_to_silence_s` / `time_to_clear_s`)
   - `medication_dispense_log` (Pyxis transactions)
   - `pump_program_log` (Alaris programs)

**Pass:** every section populated; JSON saved under
`data/debriefs/<session_id>.json`.

## Sign-off

All seven tests must pass for v6.0 to be considered LAN-ready. Record
date, tester, and tablet OS versions in `BUILD_STATE.md` after a clean
run.
