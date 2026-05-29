# M44 — Devices modal shows ONLY device manager + cabinet block (room-level med cart prep)

**Phase:** Phase 7 follow-on (post-M43, operator-feedback fix)
**Status:** **DONE** (modal scope + cabinet block); **M45 deferred** (room-level med cart UI + linking)
**Blocked by:** M42 (modal scaffold), M43 (multi-patient device routes)
**Blocks:** M45 (room-level med cart dashboard + grouped MAR)
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M43:

> "The pop up should only bring up the simulated devices, it is
> make an entire control room page. Also on Med Carts have them
> created in the Multi-Patient control and then allow them to add
> the encounters in the simulation to a specifc med cart so the
> function is no longer able to generate the med carts in the
> encounter."

Two distinct problems:

1. **The "Managed devices" modal still rendered the entire v6 ops
   view inside the iframe.** M42's embed-mode CSS hide list
   targeted class names that don't actually exist in the template
   (`.operator-ptt-card` vs the real `.op-ptt-card`,
   `.live-transcript-card` vs `.transcript-card`, etc.) — so the
   invite-stations, connected-stations, session-context, PTT,
   transcript, voices, and EHR-stations cards all stayed visible.
   The result felt "like an entire control room page" to the
   operator.

2. **Med carts (cabinets) should be a room-level resource.**
   Today every encounter can mint its own cabinet via the device
   manager. The operator wants them created once at the
   Multi-Patient Control level and then linked to encounters —
   so the per-encounter device manager should *not* let you
   generate carts.

M44 ships Phase A of both fixes:

- **(1) is fully fixed.** The devices card got an `id="devices-
  card"` anchor, and the embed-mode `<style>` block now hides
  every `.check-card` and re-shows only `#devices-card`. The
  iframe now renders the simulated-devices card and the add-device
  modal — nothing else.

- **(2) is set up but not yet wired.** The JS dropdown excludes
  the `cabinet` kind in embed mode (operator can't pick it),
  AND the `/api/device/register` route rejects encounter-scoped
  cabinet POSTs server-side with 409 + a "use Multi-Patient
  Control" hint. The actual room-level med-cart dashboard
  (creation UI + linking to encounters + grouped MAR view) is
  deferred to **M45** because it requires a model change
  (`DeviceStation.character_id → character_ids: list[str]` or a
  separate cart↔encounter join table) plus the cabinet bootstrap +
  MAR rewrite. M44 leaves the encounter side in a clean state so
  M45 can drop in the room dashboard without conflicts.

## 2. Structure

**Files touched:**

- `portal/templates/control_ops.html`:
  - Added `id="devices-card"` to the simulated-devices `<section>`.
  - Added `id="devices-card-kinds-note"` to the help text under the
    Add-device button so the JS can re-label it in embed mode.
  - Replaced the embed-mode `<style>` block with an explicit "hide
    everything, show only #devices-card" pair of declarations.
    Also kills body padding/margins + container max-widths so the
    card uses the full iframe width.

- `portal/static/control_ops_devices.js`:
  - `fillKindSelect(sel)` reads `window.MEDSIM2_OPS.embed_mode`. In
    embed mode the kind list is filtered to exclude `cabinet`. The
    help text under the button is also re-labeled to explain why
    ("Med carts are managed at the room level — add them on the
    Multi-Patient Control page").

- `portal/devices/routes.py`:
  - `POST /api/device/register` rejects `device_kind=cabinet` when
    the resolved session is an encounter in the active room (i.e.
    the route was called with `?join=<encounter join>`). Returns
    409 with the room-level hint. v6 singleton path is untouched —
    cabinets remain creatable in the legacy single-patient flow
    until the operator explicitly moves to multi-patient.

**No new dataclass field. No schema migration.** M44 is the
front-half of room-level med carts; M45 lands the model change +
new dashboard.

## 3. Uses

### 3.1 Devices modal — what the operator sees now

Before M44 (with M42's broken hide):
```
┌─ devices-dialog (iframe) ──────────────────────┐
│ [ops-view top bar: START/PAUSE/RESUME/STOP]    │  ← M42 hid this
│ [seed-report-card]                              │  ← was already hidden=hidden
│ [med-checklist-card]                            │  ← was already hidden=hidden
│ Invite stations [QR codes]                      │  ← STILL VISIBLE (bug)
│ Connected stations [roster]                     │  ← STILL VISIBLE (bug)
│ Session context [program/week/personas]         │  ← STILL VISIBLE (bug)
│ Operator PTT [hold-to-talk]                     │  ← STILL VISIBLE (bug)
│ Live transcript                                 │  ← STILL VISIBLE (bug)
│ Voices                                          │  ← STILL VISIBLE (bug)
│ EHR stations                                    │  ← STILL VISIBLE (bug)
│ Simulated devices ← the one we wanted          │
└────────────────────────────────────────────────┘
```

After M44:
```
┌─ devices-dialog (iframe) ──────────────────────┐
│                                                 │
│  Simulated devices  (3)  · 2 online            │
│  Mint a device, assign it to a character…      │
│  [+ Add device (mint QR)]                       │
│  ┌─ pump_iv · Alaris · Bed 1 IV ──────────────┐ │
│  │ status: idle    [Detail] [Inject]…         │ │
│  └────────────────────────────────────────────┘ │
│  …                                              │
│                                                 │
└────────────────────────────────────────────────┘
```

### 3.2 Add-device dropdown — cabinet excluded in embed mode

When the operator clicks **+ Add device** inside the modal, the
kind dropdown now reads:

- Pump IV (Alaris)
- Pump enteral (Kangaroo Omni)
- ~~Cabinet (Pyxis)~~  ← excluded in embed mode

And the help text under the button reads:

> Bed-level devices only (pumps + future-device buttons). Med
> carts are managed at the room level — add them on the
> Multi-Patient Control page.

### 3.3 Server-side guard

If somehow a client POSTs `device_kind=cabinet` with an
`?join=<encounter join>` (bypassing the dropdown filter), the
route returns:

```http
HTTP 409
"Med carts (cabinets) are a room-level resource. Open the
Multi-Patient Control page to add a cart, then link this
encounter to it."
```

This message is forward-pointing — when M45 lands the Multi-
Patient Control dashboard panel, the same message will be
accurate verbatim. v6 singleton (no `?join=`) is untouched.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `#devices-card` (HTML id) | `portal/templates/control_ops.html` | Stable anchor for the embed-mode CSS to show. |
| `#devices-card-kinds-note` (HTML id) | same | Help-text span the JS re-labels in embed mode. |
| `fillKindSelect(sel)` (extended) | `portal/static/control_ops_devices.js` | Filters out `cabinet` when `MEDSIM2_OPS.embed_mode` is true. |
| `POST /api/device/register` (extended) | `portal/devices/routes.py` | Rejects `device_kind=cabinet` when `?join=` resolves to a v7 encounter. |

## 5. Limitations

- **The cabinet block message references a Multi-Patient Control
  feature that does not yet exist.** Until M45 ships the room-
  level dashboard panel, the operator will see the message and
  not have anywhere to actually create the cart. The message is
  honest — it's the right path forward — but premature.
  Workaround: M44 doesn't prevent operators from creating
  cabinets in the v6 single-patient flow (no `?join=` ⇒
  unrestricted).
- **Embed-mode CSS uses `display: revert` for the `body > script`
  selector** to keep the bootstrap inline scripts running.
  Browsers without `revert` support (very old) would fall back to
  inherited display values. Not a concern for the target operator
  workstations.
- **The "show only" approach is global** — it hides everything
  except `#devices-card`. If a future v6 ops-view section is
  added without an explicit show-rule, it'll be invisible in
  embed mode. Document this in the ops-view edit comment.
- **No filter on the WS event firehose.** The instructor
  WebSocket at `/ws/instructor` still broadcasts every device
  event across the room; the embedded modal sees all of them, not
  just events from this encounter. Acceptable today (just chatter);
  M45 can scope by encounter when it lands.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_devices_modal_scope.py::test_embed_mode_css_hides_all_other_cards` | Page injects the show-only-devices-card CSS pair + body padding/margin overrides | PASS | 2026-05-27 |
| `…::test_embed_mode_does_not_apply_in_v6_single_patient_path` | Without `?embed=1`, the CSS block doesn't render — v6 path unchanged | PASS | 2026-05-27 |
| `…::test_register_cabinet_rejected_when_encounter_scoped` | `cabinet` POST with `?join=<encounter>` returns 409 with the "room-level" message | PASS | 2026-05-27 |
| `…::test_register_pump_iv_still_works_when_encounter_scoped` | `pump_iv` POST with `?join=` still 200s (only cabinet is blocked) | PASS | 2026-05-27 |
| `…::test_cabinet_block_only_fires_when_join_targets_an_encounter` | Cabinet block path is bounded — without `?join=` the session-resolution 409 fires first; the cabinet branch is unreached | PASS | 2026-05-27 |
| `…::test_devices_js_filters_cabinet_kind_in_embed_mode` | JS source carries `embed_mode` check + filter + "room level" copy | PASS | 2026-05-27 |
| **Full v7 suite** | **301 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M44: `#devices-card` anchor + show-only embed CSS; `cabinet` filtered from JS dropdown in embed mode + server-side guard on the register route; 6 new tests | `portal/templates/control_ops.html`, `portal/static/control_ops_devices.js`, `portal/devices/routes.py`, `tests/v7/test_devices_modal_scope.py` (new) |

## 8. Open questions / known issues — **M45 plan**

The full "room-level med carts + grouped MAR" feature requires:

**Data model**
- New `room.med_carts: dict[station_id, DeviceStation]` on the
  ControlRoom dataclass. Each cart's `session_id` becomes the
  room id (or a stable `room.cart_session_id`) instead of an
  encounter id.
- New cart↔encounter link table OR a `cart.linked_encounter_ids:
  list[str]` field. Multiple encounters → one cart is the new
  invariant.
- Migration of the existing `device_station` SQLite table to
  carry a `room_id` column alongside `session_id` (nullable for
  pumps/non-cart devices).

**Routes**
- `POST /api/room/med_cart/register` — operator creates a cart on
  the Multi-Patient Control dashboard.
- `POST /api/room/med_cart/{station_id}/link_encounter` — adds an
  encounter to the cart.
- `DELETE /api/room/med_cart/{station_id}/link_encounter/{eid}` —
  removes the link.
- The cart's bootstrap (`/api/device/{sid}/bootstrap`) returns a
  *list* of per-patient MAR sections (one per linked encounter's
  patient persona) instead of a single MAR.

**UI**
- Multi-Patient Control dashboard: new "🛒 Med carts" card with
  list + Add form + per-cart linked-encounters chip list +
  "Open cart" QR.
- Encounter console device modal: a "Linked med carts" read-only
  section showing which room carts this bed is attached to + an
  "Unlink" affordance.
- Cabinet device page: grouped MAR with patient name headers
  (per the operator's original ask: *"list each of the assigned
  character patients and their assigned medication under their
  character name"*).

**Migration story**
- Existing v6 single-patient cabinets keep working unchanged
  (their `linked_encounter_ids` is a 1-element list of their
  legacy session).
- v7 multi-patient: operators must create carts at the room level
  going forward. M44's server-side block is what enforces this.

M45 is sized at ~1.5 engineer-days. Tracked separately so M44 can
ship the immediate fixes today.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
