# M42 — Inline device manager in the encounter console

**Phase:** Phase 7 follow-on (post-M41, operator-feedback fix)
**Status:** **DONE** (Phase A — inline embed; Phase B/C deferred to M43)
**Blocked by:** M2 (Encounter dataclass + get_by_join_code), M22 (Per-Patient Console), M39 (modal-dialog pattern reused here)
**Blocks:** M43 (shared med carts + grouped MAR — explicitly deferred)
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M41:

> "On each encounter the device manager should be setup to operate
> within the encounter like it does for the single patient not
> having to leave the encounter through a link like it currently
> is. All the device functions and assignments should function the
> same. The assignment for a device being added should pre-populate
> with the patient Character of the encounter."

Three problems wrapped in one report:

1. **The link-out was broken in multi-patient mode**. The encounter
   console's Devices card linked to `/portal/control/ops?join=…`,
   but that route used `control_session.get_active()` — which per
   the M2 contract returns `None` in any multi-encounter room. The
   instructor clicked the link and got bounced to the wizard.
2. **The link itself was the wrong UX**. Even when it worked
   (single-patient mode), it pulled the operator out of the
   encounter console — losing telemetry, ECG, scene injector,
   transcript pane context.
3. **The add-device modal hard-coded the patient assignment to
   "— unassigned —"** (see `control_ops_devices.js:272`:
   `fillCharacterSelect($('ad-char'), '')`). Even in single-patient
   mode the operator had to re-pick the patient every time.

M42 fixes all three with three small changes:

1. `/portal/control/ops` now accepts `?join=<code>` and resolves the
   session via `control_session.get_by_join_code` first, falling
   back to `get_active()` for v6-compat. Works in multi-patient
   mode.
2. The ops route also takes `?patient_persona_id=<pid>` (override)
   and `?embed=1` (hides the ops-view header for iframe embedding).
   Falls back to the session's primary patient when no override is
   passed.
3. The encounter console's Devices card replaces the link-out with
   a **🔧 Manage devices** button that opens a modal dialog
   containing the ops view in an iframe — same pattern as M39's
   Engage modal. The iframe URL carries `?join=&embed=1` so the
   ops view renders scoped + chromeless; popout link keeps the
   non-embed URL for second-monitor workflows.

**Explicitly out of scope (deferred to M43):**
- **Shared med carts across multiple encounters.** Today a cabinet
  (`device_kind="cabinet"`, `device_model="pyxis"`) has a single
  `character_id` field — one patient per cart. The user wants one
  cart shared across multiple beds.
- **Medicine administration grouped by patient character.** Today
  the cart's MAR is seeded once per session; v7's per-patient
  grouping is a model change that depends on the shared-cart work
  above.

These two pieces are bigger architectural changes (model migration
+ MAR rewrite) and would have ballooned M42 past one module. M43
will pick them up.

## 2. Structure

**Files touched:**

- `portal/server.py` — `/portal/control/ops` route:
  - New query params: `join`, `patient_persona_id`, `embed`.
  - Resolution: `control_session.get_by_join_code(join)` → fallback
    to `control_session.get_active()` → fallback redirect.
  - Renders the template with two new keys: `default_device_patient_id`
    (resolved from query param OR `sess.patient_persona_id` OR the
    session's first selected persona) and `embed_mode` (bool).

- `portal/templates/control_ops.html`:
  - Bootstrap `window.MEDSIM2_OPS` now carries
    `default_device_patient_id` and `embed_mode`.
  - When `embed_mode` is true, a `<style>` block hides the v6
    ops-view chrome (`.topbar`, `.ops-header`, `.control-bar`,
    `.session-context-card`, `.live-transcript-card`,
    `.operator-ptt-card`, `.seed-report-card`,
    `.medication-checklist-card`). The device manager, invite-
    stations card, and connected-stations card stay visible.

- `portal/static/control_ops_devices.js` — `openAddDevice()` now
  reads `window.MEDSIM2_OPS.default_device_patient_id` and passes
  it to `fillCharacterSelect($('ad-char'), defaultPatient)` instead
  of the hard-coded empty string. Falls back to `''` when no
  default is set (v6 single-patient behavior unchanged).

- `portal/templates/encounter_console.html`:
  - Devices card's link-out swapped for a `<button id="btn-manage-
    devices">` styled as a primary blue pill.
  - New `<dialog id="devices-dialog">` near the engage-dialog with
    iframe + close button + popout anchor. Iframe starts at
    `about:blank`.

- `portal/static/encounter_console.js` — new `DOMContentLoaded`
  handler binds `#btn-manage-devices` to opening the modal. Sets
  the iframe `src` to `/portal/control/ops?join=<jc>&embed=1` and
  the popout anchor's `href` to the same URL without `embed=1`.
  Close button + native `close` event blank the iframe (same
  cleanup pattern as M39).

- `portal/static/encounter_console.css` — `.device-manage-btn`
  styled as a primary action.

**No backend dataclass change. No schema migration.** The
DeviceStation model is untouched in M42 (M43 will change it for
shared carts).

## 3. Uses

### 3.1 Operator flow

1. Operator is on a Per-Patient Console
   (`/portal/room/encounter/{id}`).
2. Scrolls to the Devices card. Sees the bound-device list (M22
   summary) + a **🔧 Manage devices** button.
3. Clicks the button. Modal dialog opens overlaying the encounter
   console. Backdrop dims the underlying console.
4. Modal iframe loads `/portal/control/ops?join=<encounter join>&
   embed=1`. The ops view's top header + transcript + ptt panel
   are hidden (embed mode). The instructor sees: invite-stations
   card (chat + EHR QR), connected-stations roster, and the device
   manager — exactly the surfaces relevant to device management.
5. Operator clicks **+ Add device** inside the iframe. The patient
   dropdown is **pre-selected to this encounter's primary patient**
   (e.g. *Mr. Hayes (P-014)*) — no need to re-pick.
6. Operator picks kind/model, optionally tweaks the patient
   assignment, hits Mint QR. Device registers via the existing
   `POST /api/device/register`. Modal stays open; new device
   appears in the iframe's roster.
7. Operator closes the modal (✕ Close button or ESC). Iframe src
   blanks (cleans up any in-flight WS connections); operator
   lands back on the encounter console.
8. The bound device shows up in the encounter console's Devices
   card on the next 2s `/api/room/state` poll.

### 3.2 Why iframe-embed vs. native inline

Native inline would require porting ~1500 LOC of working v6
device-management JS into the encounter console namespace. That's
a multi-day refactor with real risk of behavior drift. The
iframe-embed approach reuses every line of that code unchanged —
the only changes are the route's lookup path (one query param)
and the add-device default (one constant). Same trade-off M39
made for the engage chat UI.

### 3.3 Behavior matrix

| Path | Pre-M42 | Post-M42 |
|------|---------|----------|
| Single-patient ops view (`/portal/control/ops`) | works (get_active) | works (get_active fallback) |
| Multi-patient ops link-out from encounter console | **broken** (get_active=None → 303 to wizard) | works (?join=… lookup) |
| Add-device patient dropdown default | hard-coded "" (unassigned) | encounter's primary persona |
| Operator stays in encounter window | no — link-out new tab | **yes — modal overlay** |

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `GET /portal/control/ops` | `portal/server.py` | Now accepts `?join=<code>` + `?patient_persona_id=<pid>` + `?embed=1`. Backward-compatible with the v6 callsites. |
| `window.MEDSIM2_OPS.default_device_patient_id` | `portal/templates/control_ops.html` | Bootstrap field. Empty string when unscoped. |
| `window.MEDSIM2_OPS.embed_mode` | same | Bootstrap field. True when iframed. |
| `openAddDevice()` (updated) | `portal/static/control_ops_devices.js` | Reads `default_device_patient_id` from bootstrap; default arg of `fillCharacterSelect` is no longer hard-coded `""`. |
| Modal markup | `portal/templates/encounter_console.html` | `<dialog id="devices-dialog">` + iframe. |
| Button wiring | `portal/static/encounter_console.js` | DOMContentLoaded handler binds `#btn-manage-devices` → opens modal with the scoped iframe URL. |

## 5. Limitations

- **Cabinets are still single-patient.** Med carts (`device_model=
  "pyxis"`) carry one `character_id`. Shared-cart support requires
  changing the `DeviceStation` model + the cabinet's bootstrap +
  the cart's MAR rendering. M43 will pick this up.
- **The grouped per-patient MAR view doesn't exist yet.** Today
  the cabinet UI lists meds as a flat per-station list. Operators
  asked for *"each of the assigned character patients and their
  assigned medication under their character name"* — also M43.
- **Embed-mode hides the v6 PTT panel + transcript.** Those have
  v7-native equivalents on the encounter console already (the
  voice card with Engage modal from M33/M39, and the live
  transcript card). Hiding them in the iframe is a feature, not
  a regression.
- **The CSS-based header hide could miss future v6 ops-view
  elements.** If a future v6 change adds a new top-of-page
  element, it'll show up in embed mode until we list it in the
  hide block. Acceptable for now; easy to extend.
- **The patient pre-populate uses the encounter's
  `patient_persona_id`.** If the operator changes the primary
  patient on the encounter (no UI for that today), already-bound
  devices keep their old `character_id`. New devices get the new
  default. Matches the snapshotted-on-create v6 behavior.
- **The modal's iframe sandbox**: we don't set a `sandbox`
  attribute. The iframe runs same-origin so cookies + WebSockets
  work for the device manager. If a future security review wants
  isolation, the iframe's behavior would need to switch to a
  cross-origin allowlist.
- **No keyboard shortcut to open the device manager.** Click
  only. Out of scope for v7.0.
- **The button label is "Manage devices"** (not "Manage devices
  and medications") even though the modal also exposes the
  medication checklist. Acceptable — meds-as-devices is a fuzzy
  line.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_inline_device_manager.py::test_ops_view_loads_via_join_code_in_multi_encounter_room` | `/portal/control/ops?join=<bed join>` returns 200 in a 2-encounter room (broken pre-M42) | PASS | 2026-05-27 |
| `…::test_ops_view_with_unknown_join_falls_back_to_wizard` | Unknown join → 303 to /portal/control (no get_active() session) | PASS | 2026-05-27 |
| `…::test_ops_view_bootstrap_pre_fills_patient_persona_from_query` | `?patient_persona_id=P-014` → bootstrap carries `default_device_patient_id=P-014` | PASS | 2026-05-27 |
| `…::test_ops_view_bootstrap_falls_back_to_session_primary` | Without override, defaults to session's patient persona | PASS | 2026-05-27 |
| `…::test_ops_view_embed_mode_hides_top_header` | `?embed=1` injects a `<style>` block hiding `.topbar` etc | PASS | 2026-05-27 |
| `…::test_device_js_uses_default_patient_on_add_device` | `openAddDevice()` reads `default_device_patient_id` and passes it to `fillCharacterSelect` | PASS | 2026-05-27 |
| `…::test_encounter_console_renders_manage_devices_button` | Devices card has `#btn-manage-devices`; old link-out is gone | PASS | 2026-05-27 |
| `…::test_encounter_console_devices_modal_present` | `<dialog id="devices-dialog">` + iframe + close + popout markup present; iframe starts at `about:blank` | PASS | 2026-05-27 |
| `…::test_devices_dialog_popout_href_is_scoped_to_encounter` | Popout anchor href has `join=<code>` + `patient_persona_id=<pid>` | PASS | 2026-05-27 |
| `…::test_encounter_console_js_wires_manage_devices_button` | `encounter_console.js` binds the button, builds the embed URL, blanks the frame on close | PASS | 2026-05-27 |
| **Full v7 suite** | **284 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M42 (Phase A): ops route accepts `?join`+`?patient_persona_id`+`?embed`; bootstrap carries them; device-add JS reads the patient default; encounter console gets a `#btn-manage-devices` button + `<dialog id="devices-dialog">` + iframe modal; CSS for the button; 10 new tests | `portal/server.py`, `portal/templates/control_ops.html`, `portal/static/control_ops_devices.js`, `portal/templates/encounter_console.html`, `portal/static/encounter_console.{js,css}`, `tests/v7/test_inline_device_manager.py` (new) |

## 8. Open questions / known issues

- **M43 — Shared med carts across encounters.** The DeviceStation
  model needs a `character_ids: list[str]` field (or a separate
  `cabinet_assignments` table linking cart_id ↔ encounter_id). The
  cart's bootstrap response (`/api/device/<sid>/bootstrap`) needs
  to return a list of patient MARs, not one. The cabinet UI needs
  a per-patient section header.
- **M43 — Grouped MAR view.** Each patient gets a labeled section
  in the cart UI showing their meds (name, dose, route, status).
  Dispensing logs to the per-patient `chart_event` with the
  current patient context. Migration: existing single-patient
  carts become single-element lists transparently.
- **M43 — UI for shared-cart assignment.** A new "+ Assign
  additional patient" button on the device-detail modal would
  add another encounter to the cart's `character_ids`. Today's
  M42 inline manager will show the M43 capability automatically
  once the backend ships.
- **Embed-mode CSS coverage.** The hide list in
  `control_ops.html`'s `{% if embed_mode %}` block hides what's
  visible today. A future operator-facing review (LAN test) may
  surface other v6 elements that should be hidden in the modal.
- **The popout anchor is generated server-side with the encounter's
  `patient_persona_id` baked in.** If the operator later changes
  the primary patient (no UI today), the popout link stales until
  page refresh. Acceptable; documented.
- **Browser back-button inside the iframe**. If the operator
  navigates within the iframe and then hits browser back, behavior
  depends on the browser's iframe history isolation. Verify in
  LAN test if anyone hits this.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
