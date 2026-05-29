# M45 — Inline device control cards in the encounter Devices card

**Phase:** Phase 7 follow-on (post-M44, operator feature request)
**Status:** **DONE**
**Blocked by:** M22 (Devices-card scaffold), M43 (device routes multi-patient aware), M44 (modal scope + cabinet block)
**Blocks:** none (room-level cart UI still tracked separately)
**Estimated effort:** 0.75 day

---

## 1. Purpose

Operator feature request:

> "Once the device is added the control system for the device
> should populate in the device area of the encounter for easy
> access of the instructor."

Before M45, the encounter console's Devices card was display-only:
it polled `/api/room/state` every 2 s and rendered a count summary
("3 device station(s) bound · 0 chat · 1 EHR · 3 device station(s)").
To actually CONTROL a bound device — inject an alarm, clear it,
reassign the patient, advance the pump's clock — the instructor
had to reopen the M42/M44 *Managed devices* modal every time.

M45 inlines the full control surface. After a device is added (via
the modal — that's the right place to mint a QR), it shows up in
the Devices card as a card-style row with its own:

- Device kind icon + label + model + online/offline indicator + runtime state
- Patient-assignment dropdown (reassign without opening the modal)
- Active alarm list with per-alarm **Clear** buttons + a **Clear all** button
- Alarm-tone picker + **⚠ Inject** button (server-validated tone list)
- For pumps: **+5m / +15m / +1h** advance-time buttons

The modal stays for adding new devices (mint QR + assign label). All
everyday operations now happen in place.

## 2. Structure

**Files touched:**

- `portal/static/encounter_console.js`:
  - `pollState()` no longer paints the Devices card — it's
    refocused on the encounter state badge.
  - New `pollDevices()` polls `/api/device/roster?join=<jc>` (the
    M43 multi-patient-aware route).
  - New `renderDeviceCards(stations)` and `renderDeviceCard(s)`
    paint the per-device markup.
  - New action handlers `onDeviceAction(el)` (inject / clear-one /
    clear-all / advance-time) and `onDeviceAssign(sel)` (reassign).
    All call the per-station device routes — which since M43 work
    in multi-patient mode via `station.session_id`.
  - New `DEVICE_TONE_CATALOG` keyed by device_kind. Tone IDs match
    the server-side `PUMP_ALARMS` / `CABINET_ALERTS` catalogs in
    `portal/devices/engine/alarms.py` (curated subset of the most
    common training tones — server validates).
  - New `KIND_LABEL` for friendly icons + names (💧 IV pump,
    🛒 Med cart, 🔔 Call bell, etc.).
  - New `personaNameFor(pid)` helper that resolves persona display
    names from the cached `encVoiceBody.personas` array (built by
    M33's `bootVoices`).
  - `startPolling()` now launches a third timer (`devicesTimer`)
    on its own 3 s cadence. The roster fold is slightly heavier
    than the 2 s state/transcript poll (each station does an
    engine.fold + alarm scan), so we space it out.

- `portal/static/encounter_console.css`:
  - Appended `.device-card` block style (overrides the older
    `.device-list li { display: flex }` that would have wrapped
    the card contents horizontally).
  - `.device-card-header` / `.device-card-meta` / `.dev-dot`
    (online/offline indicator) / `.device-card-assignment` /
    `.dev-alarm-list` / `.dev-tone-picker` / `.dev-btn-sm` /
    `.dev-btn-inject` / `.dev-time-group`.

**No backend change. No new HTML template markup.** The encounter
console's existing `<ul id="device-list">` (M22 scaffold) is the
container; M45 just renders richer markup into it.

## 3. Uses

### 3.1 Operator flow

1. Operator opens the encounter console. The Devices card renders
   *"No devices bound to this encounter."*
2. Clicks **🔧 Managed devices** → modal opens (M42/M44) → operator
   picks pump_iv + Alaris + label, clicks Mint QR. Hands the QR to
   a student tablet.
3. Closes the modal. Within 3 s, the encounter console's Devices
   card renders the new pump as a card row:
   ```
   ┌─ 💧 IV pump · Bed 1 IV ─────────────── ● idle ────┐
   │ Patient: [Mr. Hayes ▾]              dev_abc123     │
   │ [▾ occlusion_downstream ] [⚠ Inject]               │
   │                                       [+5m][+15m][+1h] │
   └────────────────────────────────────────────────────┘
   ```
4. Operator picks `occlusion_downstream` in the tone picker,
   clicks **⚠ Inject**. The route `POST /api/device/<sid>/inject`
   fires; the device tablet's WebSocket pushes the new state in
   under a second; the encounter console's next 3 s poll shows the
   active alarm in a yellow alarm-list block with a **Clear**
   button next to the tone.
5. Operator clicks **Clear**. The route `POST /api/device/<sid>/
   clear` fires; the next poll removes the alarm row.
6. Operator picks a different patient in the dropdown. The route
   `POST /api/device/<sid>/assign` fires; the persisted assignment
   updates.
7. For pumps with an active infusion, **+5m / +15m / +1h** buttons
   call `POST /api/device/<sid>/advance_time` to fast-forward the
   pump clock (training acceleration — saves 4 h of real-time
   waiting on a real-life infusion).

### 3.2 Polling cadence

| Loop | Cadence | What it fetches |
|------|---------|-----------------|
| Telemetry (M22/M23) | 1 s | `GET /api/encounter/{id}/telemetry` |
| State + transcript (M22/M30) | 2 s | `/api/room/state` + `/api/encounter/{id}/transcript` |
| **Devices (M45)** | **3 s** | `/api/device/roster?join=<jc>` |

The polls share the `visibilitychange` pause hook — when the
console tab is hidden, all three timers stop.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `pollDevices()` (new) | `portal/static/encounter_console.js` | Fetches `/api/device/roster?join=<jc>`, hands to renderer. |
| `renderDeviceCards(stations)` (new) | same | Maps each station to a card LI. |
| `renderDeviceCard(s)` (new) | same | Per-station card markup. |
| `onDeviceAction(el)` (new) | same | Handles inject / clear-one / clear-all / advance from the per-card buttons. |
| `onDeviceAssign(sel)` (new) | same | Patient-reassign dropdown handler. |
| `DEVICE_TONE_CATALOG` (new) | same | Per-kind tone list — must match server alarms.py catalog. |
| `KIND_LABEL` (new) | same | Per-kind friendly label with emoji. |

## 5. Limitations

- **Cabinet (med cart) reassignment is not exposed inline.** The
  card shows a *"Med cart (room-level)"* note under the
  assignment dropdown. The full shared-cart UI ships in the
  deferred M44-§8 work (room-level med carts + linking + grouped
  MAR).
- **Hard-coded tone catalog**. If the server adds new tones in
  `alarms.py` they won't appear in the dropdown until the JS
  catalog is updated. Server validates every inject so a stale
  client gets a clear 400. A future M46 could fetch the catalog
  from a new `/api/device/tones` route.
- **No WS push.** The card refreshes on the 3 s poll. WS push
  for sub-second updates exists at `/ws/instructor` (M16-era);
  wiring it would replace the polling loop. Out of scope; the
  M22 polling cadence is the bedside-station latency budget
  anyway.
- **Persona dropdown reuses `encVoiceBody.personas`** populated
  by `bootVoices()`. If `bootVoices()` failed (e.g. server returned
  4xx), the dropdown only shows "— unassigned —". That matches
  the v6 behavior; the operator can still reassign by id via the
  Managed-devices modal.
- **`advance_time` buttons are pump-only.** Cabinets and future-
  device buttons don't have a clock to advance. The buttons are
  conditionally rendered.
- **Polling is per-tab.** Two operators on different machines
  each poll independently. Acceptable; same as M22.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_inline_device_cards.py::test_encounter_js_has_pollDevices_function` | `pollDevices`, `/api/device/roster?join=`, `renderDeviceCards` in source | PASS | 2026-05-27 |
| `…::test_encounter_js_renders_per_device_card_with_controls` | All 5 action data-attrs (inject, clear-one, clear-all, advance, assign) present | PASS | 2026-05-27 |
| `…::test_encounter_js_wires_actions_to_device_routes` | `onDeviceAction` calls `/inject`, `/clear`, `/advance_time`; `onDeviceAssign` calls `/assign` | PASS | 2026-05-27 |
| `…::test_encounter_js_tone_catalog_covers_supported_kinds` | Catalog covers pump_iv / pump_enteral / cabinet with real tone IDs (occlusion_downstream, low_battery, discrepancy_alert) | PASS | 2026-05-27 |
| `…::test_encounter_js_polls_devices_on_its_own_cadence` | `startPolling` launches `pollDevices` with `DEVICES_POLL_MS`; `stopPolling` clears `devicesTimer` | PASS | 2026-05-27 |
| `…::test_encounter_js_does_not_call_assignment_dropdown_on_cabinet_inline` | Cabinet rows include the room-level note | PASS | 2026-05-27 |
| `…::test_device_roster_returns_full_card_shape` | `/api/device/roster?join=` returns station_id, device_kind, device_model, label, online, character_id, active_alarms, runtime_state | PASS | 2026-05-27 |
| `…::test_inject_endpoint_returns_ok_in_multi_patient` | `POST /api/device/<sid>/inject` returns 200+`ok=true` with a real tone ID | PASS | 2026-05-27 |
| `…::test_encounter_console_devices_card_has_list_anchor` | Devices card still has `#device-list` UL + `#btn-manage-devices` button | PASS | 2026-05-27 |
| **Full v7 suite** | **310 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M45 implementation: `pollDevices`, `renderDeviceCards`, `renderDeviceCard`, `onDeviceAction`, `onDeviceAssign`; `DEVICE_TONE_CATALOG` + `KIND_LABEL`; 3 s poll cadence; device-card CSS; 9 new tests | `portal/static/encounter_console.js`, `portal/static/encounter_console.css`, `tests/v7/test_inline_device_cards.py` (new) |

## 8. Open questions / known issues

- **WS push instead of poll.** `/ws/instructor` already broadcasts
  every device event; wiring it to the inline cards would give
  sub-second alarm/clear/assign updates. A future M46 could swap
  the polling loop for a WS subscriber (with poll as fallback when
  WS disconnects).
- **Tone-catalog drift.** Defer the *fetch catalog from server*
  refactor until either the catalog grows past ~12 tones per kind
  OR a tone gets renamed server-side. Today the curated subset
  covers the high-frequency training alarms.
- **Shared med carts + grouped MAR** still tracked separately as
  the M44-§8 deferred work. M45 unblocks everyday device operations;
  the shared-cart UI is independent and queued for a future module.
- **Advance-time when no channel is running** returns 200 from
  the server but the pump's `running_channels` list stays empty.
  The card doesn't surface that "applied = 0 minutes" feedback
  yet — operator would need to look at the v6 device-detail
  modal in the Managed-devices iframe. Low priority.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
