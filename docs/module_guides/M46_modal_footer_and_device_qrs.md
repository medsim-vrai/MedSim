# M46 — Hide ops-controls footer in modal + device QRs inline + on the print sheet

**Phase:** Phase 7 follow-on (post-M45, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M41 (QR print sheet), M42 (modal scaffold), M44 (modal-scope embed CSS), M45 (inline device cards)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M45:

> "On the device pop up page remove the control buttons in the
> footer of the page like run, pause, stop... etc. Also the QR
> code for the device created should populate in the encounter
> page to make it easier to use and be able to print out as part
> of the QR print out list."

Two distinct asks:

1. **Hide the `.ops-controls` footer** in the embed-mode modal.
   M44's CSS hid most of the v6 ops-view chrome, but it missed
   the `<div class="ops-controls">` footer at the bottom of
   `control_ops.html` (Pause / Resume / Preview debrief / End
   scenario / Kill switch buttons) PLUS its explanatory paragraph.
   The operator saw session-level controls that conflict with the
   M35 per-encounter Start/Pause/End in the parent console header.

2. **Surface device QRs in two places:**
   - **Inline** on each M45 device card in the encounter Devices
     area, so the operator can scan a phone at the cart right from
     the console.
   - **Printable** on the M41 QR sheet, so when the operator prints
     the encounter's QR sheet they get the device QRs to stick on
     the actual hardware.

## 2. Structure

**Files touched:**

- `portal/templates/control_ops.html`:
  - Extended the embed-mode `<style>` block with a new rule:
    ```css
    .ops-controls,
    .ops-controls + p {
      display: none !important;
    }
    ```
    The `+ p` adjacent-sibling selector kills the explanation
    paragraph below the buttons too. Conditional under
    `{% if embed_mode %}` so the v6 single-patient ops view (no
    `?embed=1`) keeps the controls.

- `portal/static/encounter_console.js`:
  - `renderDeviceCard(s)` now appends a `.device-card-qr` block
    immediately after the card header. The QR `<img>` hits
    `/api/qr.svg?data=…` with a server-style device-join URL
    (`${window.location.origin}/device/join?code=${joinCode}&station=${sid}`).
    Below the QR is the URL in monospace for typed fallback.

- `portal/static/encounter_console.css`:
  - New `.device-card-qr` / `.device-card-qr-img` /
    `.device-card-qr-url` styles. Compact strip (56px QR + URL),
    light-blue background to distinguish from the alarm block.

- `portal/server.py` (`portal_control_qr_print`):
  - Each encounter view now includes a `devices: list[dict]`
    field. For each bound device station the dict carries
    `station_id`, `device_kind`, `device_model`, `label`. The
    print template uses this list to render per-device QR blocks.

- `portal/templates/qr_print.html`:
  - New `.device-qr-section` block under each encounter's four
    station QRs, gated by `{% if enc.devices %}`. Renders a 3-
    column grid (slightly tighter than the station QRs since
    devices usually have shorter labels). Each block: label,
    `kind · model` sublabel, 1.4-inch QR, and the URL in
    monospace. CSS includes `page-break-inside: avoid` so a
    device block doesn't get split across pages.

**No backend route change. No new dataclass field.** All data was
already exposed via `enc.device_stations`.

## 3. Uses

### 3.1 The `.ops-controls` footer fix

Before M46, opening the Managed-devices modal in v7 multi-patient
mode showed (despite M44's CSS):
```
┌─ devices-dialog (iframe) ─────────────────────────┐
│ ...                                                │
│  Simulated devices                                 │
│  [+ Add device]                                    │
│  [pump card + cabinet card]                        │
│                                                     │
│  [⏸ Pause]  [▶ Resume]  [📊 Preview debrief]      │
│  [✓ End scenario]   [⛔ Kill switch]               │  ← leaked through
│                                                     │
│  End scenario normally finishes the session and... │  ← leaked through
└────────────────────────────────────────────────────┘
```

The operator sees session-level controls that conflict with the
M35 *▶ Start · ⏸ Pause · ⏹ End* buttons in the parent encounter
console's header — two competing control surfaces for the same
underlying state.

After M46, the modal renders just the simulated-devices card and
the add-device modal. The session controls live exclusively on
the parent encounter console (M35).

### 3.2 Inline device QR

After a device is added via the modal, the next 3 s `pollDevices()`
tick (M45) re-renders the device card with the QR strip:

```
┌─ 💧 IV pump · Bed 1 IV ──────────── ● idle ──┐
│ [QR ]  http://192.168.1.50/device/join?      │
│ [img]  code=7J7AVM&station=dev_abc123        │
│ Patient: [Mr. Hayes ▾]          dev_abc123    │
│ [▾ occlusion_downstream] [⚠ Inject]           │
│                            [+5m][+15m][+1h]   │
└──────────────────────────────────────────────┘
```

The operator can scan the QR with a phone right at the
encounter console — no need to walk back to the modal where the
mint-time QR was originally shown.

### 3.3 Device QRs on the print sheet

The M41 print sheet was already showing 4 station QRs per
encounter (Chat / EHR / Device / Nursing). M46 adds a new
`📟 Devices ({{N}})` section under those four, with one block per
bound device. The section only renders when there's at least one
device (`{% if enc.devices %}`).

The operator can now print one sheet per encounter and:
- Hand the 4 station QRs to students
- Stick the per-device QRs on the actual hardware (cart, pump)

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `.ops-controls` hide rule | `portal/templates/control_ops.html` `{% if embed_mode %}` block | Hides the v6 session control footer in modal-embed mode. |
| `renderDeviceCard(s)` (extended) | `portal/static/encounter_console.js` | Now renders a `.device-card-qr` strip with a server-style device-join URL. |
| Encounter `devices` view | `portal/server.py portal_control_qr_print` | New field on the print template's encounter dict carrying `station_id` / `device_kind` / `device_model` / `label` per bound device. |
| Per-device print block | `portal/templates/qr_print.html` `{% if enc.devices %}` | Renders `.device-qr-section` with per-device QR blocks. |

## 5. Limitations

- **The inline device QR uses `window.location.origin`** as the
  base URL. That's correct when the operator opens the encounter
  console on the LAN host the bedside phones are reaching, but
  wrong if the operator opens the console via a different host
  (e.g. an SSH tunnel). Mitigation: the URL is also visible in
  monospace under the QR — operator can verify it matches the
  base URL the device tablet will reach.
- **No device card on the v6 ops view's roster** is changed.
  M46 only touches the encounter-console inline cards and the
  print sheet. The v6 ops view's device cards (visible in the
  modal iframe) still have their own QR popup via the device
  detail modal.
- **Print sheet layout** uses 3-column grid for device QRs. If a
  bed has many devices (10+) the section grows tall; CSS
  `page-break-inside: avoid` keeps individual blocks atomic but
  the section as a whole may flow past the encounter's first
  page. Acceptable; the patient header is still readable on the
  device-only continuation page.
- **The `.ops-controls + p` selector** depends on the
  explanation paragraph being the immediate sibling of
  `.ops-controls`. If a future v6 template edit inserts another
  element between them, the paragraph re-appears. Add to the
  hide list if that happens.
- **WS-pushed device additions** still trigger an inline card
  re-render only on the next 3 s poll. The print sheet is
  fetched on demand — operator must re-open the sheet to see
  new devices.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_device_qr_and_modal_footer.py::test_embed_mode_hides_ops_controls_footer` | `?embed=1` page CSS contains `.ops-controls` + `.ops-controls + p` hide rules | PASS | 2026-05-27 |
| `…::test_embed_mode_hide_block_unchanged_without_embed_flag` | Without `?embed=1` the hide rule isn't injected (v6 path unchanged) | PASS | 2026-05-27 |
| `…::test_inline_device_card_includes_qr_strip` | `renderDeviceCard` markup has `.device-card-qr` + `.device-card-qr-img` + `/api/qr.svg?data=` + `/device/join?code=` + `&station=` | PASS | 2026-05-27 |
| `…::test_inline_device_card_qr_uses_encounter_join_code` | QR URL is built from `cfg.joinCode` (the encounter's join code), not hard-coded | PASS | 2026-05-27 |
| `…::test_qr_print_renders_device_qr_per_encounter` | After registering a device, the print sheet renders the device's label + kind + model + QR URL | PASS | 2026-05-27 |
| `…::test_qr_print_omits_device_section_when_no_devices` | Encounter with no devices → no `📟 Devices` section | PASS | 2026-05-27 |
| `…::test_qr_print_route_passes_devices_view_per_encounter` | Two devices on one bed both render with their station ids + labels | PASS | 2026-05-27 |
| **Full v7 suite** | **317 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M46: embed-mode hides `.ops-controls`+sibling paragraph; inline device cards render a QR strip; print sheet carries per-device QR section; 7 new tests | `portal/templates/control_ops.html`, `portal/static/encounter_console.{js,css}`, `portal/server.py`, `portal/templates/qr_print.html`, `tests/v7/test_device_qr_and_modal_footer.py` (new) |

## 8. Open questions / known issues

- **Base-URL detection** for the inline device QR uses
  `window.location.origin`. If a future deployment puts the
  operator workstation behind a reverse proxy with a different
  external host, the QR encodes the proxy URL which may not be
  what the bedside phone reaches. The server-rendered QRs on the
  print sheet use `_base_url_for_qr(request)` which already
  handles this (it prefers the LAN IP over the request's Host
  header). A future fix could expose a JSON endpoint that the
  encounter console fetches once at boot for the canonical base
  URL.
- **Device QR refresh** on the inline card uses cache-busting via
  the URL params (different station_id → different QR). If a
  device is deleted and re-added with the same id (unlikely —
  station_ids are tokens), the browser might cache the old QR.
  Acceptable; standard `<img>` cache behavior.
- **Print sheet section position**. Today devices are at the
  bottom under the 4 station QRs. Some operators may want the
  device QRs above (closer to where the patient banner is).
  Defer to LAN-test feedback.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
