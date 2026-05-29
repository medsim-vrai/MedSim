# M41 — Printable QR sheet for the instructor

**Phase:** Phase 7 follow-on (post-M40, operator-feature request)
**Status:** **DONE**
**Blocked by:** M2 (Encounter dataclass + room_code), M22 (Per-Patient Console), M31 (per-encounter QR card with all 3 station URLs), M36 (Nursing Station QR pattern)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feature request:

> "The instructor should have the option of printing out a page of
> QR codes for related to each encounter, for any devices,
> characters, records management. The instructor should be able to
> select printing all the QR codes for each encounter or select a
> single encounter. Each QR code should be clearly labeled and if
> any codes are needed to sign in and join that should also be
> printed at the top. The Patient Character should also be on the
> header and the header should have a title 'Training Bridge
> MedSim-VRAI'."

Implementation: new `/portal/control/qr_print` route that renders
a print-friendly sheet. One page per encounter; optional
`?encounter_id=…` query param scopes to a single bed.

Each page carries:

1. **Title bar**: *"Training Bridge MedSim-VRAI"* in large brand
   color, with a *"Multi-patient simulation — station join sheet"*
   subtitle.
2. **Patient character banner**: the persona's display name + id +
   role in a warm-yellow banner so it's the first thing anyone
   reading the sheet sees.
3. **Sign-in codes block**: the room code + the bed's join code
   in a typed-friendly monospace, plus the EHR system id when
   configured. These are what someone manually types when the QR
   can't be scanned.
4. **QR grid** — four blocks (2×2): Chat station, EHR station,
   Device station, Nursing Station. Each block has a label, a
   one-line description, the QR image (`/api/qr.svg?data=…`), and
   the URL printed underneath in monospace.
5. **Page-break-after** between encounters so each bed gets its
   own sheet of paper.

Two launch buttons:
- **Multi-Patient Control header** → **🖨 Print QR codes** →
  `/portal/control/qr_print` (all encounters, new tab).
- **Per-Patient Console QR card footer** → **🖨 Print QR codes for
  this encounter** → `/portal/control/qr_print?encounter_id={id}`
  (just this bed, new tab).

The new tab carries a "🖨 Print" action button at the top. The
operator clicks Print → browser print dialog → paper or save-as-
PDF. The action bar is hidden via `@media print` so it doesn't
land on the printed page.

## 2. Structure

**Files touched:**
- `portal/templates/qr_print.html` (new) — full standalone HTML
  page (does NOT extend `base.html` — we don't want the portal
  nav on the printed sheet). Inline CSS sets `@page` size +
  margins, a screen-only off-page background, page-break-after
  per `.qr-page`, and a `@media print` block that strips the
  off-page chrome.
- `portal/server.py` — new route
  `GET /portal/control/qr_print` (instructor-only via
  `Depends(auth.require_vault)`). Optional `encounter_id` query
  param. Resolves the active room, filters out private-clone
  per-student clones (template encounters are what the operator
  cares about for QR distribution), and hydrates each encounter
  with its patient persona's display name via `library.get_persona`.
  Renders the template with `room_code`, `encounters`,
  `base_url`, `scope_label`. Handles "no active room" gracefully
  (empty notice).
- `portal/templates/control_room.html` — new `<a id="btn-qr-print">`
  in the room top bar, between the scene-inject button and the
  cohort-debrief button.
- `portal/templates/encounter_console.html` — new
  `<a class="qr-print-link">` in the QR-codes card's footer
  (scoped to this encounter via `?encounter_id={{ encounter.id }}`).
- `portal/static/control_room.css` — `.room-topbar a#btn-qr-print`
  styled to match the other `.secondary` buttons.
- `portal/static/encounter_console.css` — `.qr-print-link` styled
  as a primary blue pill button.

**No backend schema change.** No new dataclass field.

## 3. Uses

### 3.1 Operator print-all flow

1. Operator opens `/portal/room` (Multi-Patient Control).
2. Clicks **🖨 Print QR codes** in the header.
3. New tab opens at `/portal/control/qr_print`.
4. Each encounter renders as one printable page with:
   - "Training Bridge MedSim-VRAI" title bar.
   - Patient character banner (e.g. *"Patient character: Mr. Hayes
     (P-014 · Hyperactive Delirium)"*).
   - Sign-in codes: room code `2632B8`, bed join code `7J7AVM`,
     EHR system `helix`.
   - Four QR blocks: Chat / EHR / Device / Nursing Station.
5. Operator hits **🖨 Print** (top of page) or Cmd/Ctrl+P.
6. Browser opens its print dialog. Operator chooses printer or
   saves as PDF. Each encounter is one page of the output.

### 3.2 Per-encounter print flow

1. Operator opens `/portal/room/encounter/{id}` (Per-Patient
   Console).
2. Scrolls to the QR-codes card.
3. Clicks **🖨 Print QR codes for this encounter** in the footer.
4. New tab opens at `/portal/control/qr_print?encounter_id={id}`.
5. One page renders — just this bed's encounter.
6. Same Print flow.

### 3.3 What's on each printed page

```
┌─────────────────────────────────────────────────────────┐
│  Training Bridge MedSim-VRAI                            │
│  MULTI-PATIENT SIMULATION — STATION JOIN SHEET          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Patient character: Mr. Hayes  (P-014 · …)      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─ Bed 1 — ED sepsis ────────────────────────────┐     │
│  │  ROOM CODE  2632B8   BED JOIN CODE  7J7AVM     │     │
│  │  EHR SYSTEM helix                              │     │
│  └────────────────────────────────────────────────┘     │
│                                                         │
│  ┌─────────────────┐    ┌─────────────────┐             │
│  │ 💬 Chat station  │    │ 📋 EHR station   │             │
│  │ [   QR IMG   ]  │    │ [   QR IMG   ]  │             │
│  │ host/join?code=…│    │ host/ehr/join?…│             │
│  └─────────────────┘    └─────────────────┘             │
│                                                         │
│  ┌─────────────────┐    ┌─────────────────┐             │
│  │ ⚕ Device station │    │ 🩺 Nursing Station│             │
│  │ [   QR IMG   ]  │    │ [   QR IMG   ]  │             │
│  │ host/device/…   │    │ host/…?code=ROOM│             │
│  └─────────────────┘    └─────────────────┘             │
└─────────────────────────────────────────────────────────┘
```

The Nursing Station block is tinted green and its sublabel says
*"Supervisor view — uses the room code, not the bed join code"* so
the operator handing the sheet to a nursing-station tablet doesn't
type the wrong code.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `GET /portal/control/qr_print` | `portal/server.py` | Renders the print sheet. Optional `?encounter_id=<id>` scopes to one bed. 404 on unknown encounter; renders an empty notice when there's no active room. |
| `portal/templates/qr_print.html` | (new) | Standalone HTML — doesn't extend base.html (no portal nav on printed paper). Inline CSS with `@page` + `@media print` + page-break-after. |

## 5. Limitations

- **Private-clone clones are skipped.** When `chart_mode ==
  "private_clone"` and `cloned_from_id` is set, the encounter is
  a per-student clone of a template. The print sheet shows only
  the template encounter (the one the operator authored). Clones
  inherit the template's QR codes anyway. Acceptable; matches the
  M13 model.
- **Persona name comes from `library.get_persona()`.** If the
  persona ID is not in the canonical 24-persona library (defensive
  edge), the name is empty and the banner shows just the id. Same
  pattern as the M33 voices endpoint.
- **Page size hard-coded to US Letter portrait.** International
  operators wanting A4 can change the print dialog's "Paper size"
  in the browser; `@page size: letter portrait` is the *suggested*
  default, not enforced. A future M42 could read the user-agent's
  locale.
- **Each page is one encounter.** With a 10-encounter room, that's
  10 sheets. Could fit two encounters per page on a denser
  layout, but the user explicitly asked for clear labels + per-
  encounter QR sets, so one-encounter-per-page is the cleaner
  default.
- **QR codes are SVG via `/api/qr.svg?data=…`.** Same endpoint as
  M31's on-screen QRs. SVG prints crisply at any resolution. If
  the printer rasterizes oddly, a future M42 could switch to PNG.
- **No CSV export of the codes themselves.** Operators wanting a
  digital ledger of room/join codes can save the print page as
  PDF — the codes are in plain text in the headers. CSV is out of
  scope for v7.0.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_qr_print_sheet.py::test_qr_print_route_returns_branded_print_page` | Page contains brand title, print action, back link, `page-break-after`, `@media print` | PASS | 2026-05-27 |
| `…::test_qr_print_route_renders_all_encounters_by_default` | All encounters' join codes present + scope label says "all N encounters" | PASS | 2026-05-27 |
| `…::test_qr_print_route_scoped_to_single_encounter` | With `?encounter_id`, only that bed's join code is in the output | PASS | 2026-05-27 |
| `…::test_qr_print_route_404_on_unknown_encounter` | Unknown encounter id → 404 | PASS | 2026-05-27 |
| `…::test_qr_print_route_handles_no_active_room` | No active room → 200 with empty notice (no 500) | PASS | 2026-05-27 |
| `…::test_qr_print_page_carries_patient_character_in_header` | "Mr. Hayes" + persona ids appear; "Patient character" label appears | PASS | 2026-05-27 |
| `…::test_qr_print_page_carries_room_and_join_codes` | Both room code + bed join code rendered with "Room code" + "Bed join code" labels | PASS | 2026-05-27 |
| `…::test_qr_print_page_renders_all_four_station_qrs_per_encounter` | Chat / EHR / Device / Nursing labels + URLs all present; Nursing uses ROOM code | PASS | 2026-05-27 |
| `…::test_qr_print_page_qr_imgs_use_api_qr_svg_endpoint` | QR `<img>` tags target `/api/qr.svg?data=` | PASS | 2026-05-27 |
| `…::test_multi_patient_control_header_has_print_qr_button` | `/portal/room` has `#btn-qr-print` anchor → `/portal/control/qr_print` with `target=_blank` | PASS | 2026-05-27 |
| `…::test_encounter_console_has_per_encounter_print_link` | Per-Patient Console QR card has `.qr-print-link` → `/portal/control/qr_print?encounter_id=<id>` | PASS | 2026-05-27 |
| **Full v7 suite** | **274 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M41 implementation: print template + `/portal/control/qr_print` route + two launch buttons; 11 new tests | `portal/templates/qr_print.html` (new), `portal/server.py`, `portal/templates/control_room.html`, `portal/templates/encounter_console.html`, `portal/static/control_room.css`, `portal/static/encounter_console.css`, `tests/v7/test_qr_print_sheet.py` (new) |

## 8. Open questions / known issues

- **Print as PDF and attach to course materials?** The browser's
  "Save as PDF" already does this. If operators want a server-
  rendered PDF download (so they can email or attach without
  going through the browser), a future M42 could add a `?format=
  pdf` variant using `weasyprint` (already a dependency for the
  module-guide PDF renderer).
- **Future-device QR codes (call bell, bed alarm, code blue, fire
  alarm)?** M29 future-device stubs press via the encounter
  console's `/api/encounter/{id}/future_device/{kind}/press` —
  there's no separate join URL for them. If a future module adds
  hardware bindings (real call bells on real devices), the print
  sheet should add a 5th block.
- **Operator-customized header.** Some classrooms may want the
  school logo + course code in the header. Hard-coded today; a
  future M42 could read a customization JSON from `~/.medsim/v7/
  brand.json`.
- **Localization.** Title + labels are English only. Acceptable
  for v7.0; a future M42 could externalize.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
