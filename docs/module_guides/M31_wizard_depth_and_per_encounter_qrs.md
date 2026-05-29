# M31 — Multi-patient wizard depth + per-encounter QR codes

**Phase:** Phase 7 follow-on (post-M30)
**Status:** **DONE**
**Blocked by:** M5 (room wizard), M6 (mode toggle), M9 (chat join code), M22 (Per-Patient Console scaffold), M30 (per-encounter parity)
**Blocks:** none (closes the multi-patient parity loop with the single-patient ops view)
**Estimated effort:** 1 day

---

## 1. Purpose

In Room-of-N mode, the multi-patient wizard previously asked the
instructor for a *single* set of choices that applied to every bed:
one persona list, one curriculum module set, one program/week. It
also dropped the instructor at the dashboard with no per-encounter
QR codes — every bed shared the same "join the room" QR.

M31 closes the parity loop with the single-patient ops view. The
wizard now lets the instructor open three drawers per row (Scenario
/ Characters / Curriculum), each authoring per-bed:

- **Scenario** — already present from the M30-era bugfix (per-row
  scenario name + EHR + primary patient persona + chart-mode + label).
- **Characters** — multi-select of the 24 canonical personas, so
  Bed 1 can be `patient + MD + charge RN` while Bed 2 is
  `patient + parent`. The primary patient persona is always
  included automatically.
- **Curriculum** — per-bed program (`ADN-RN`, `BSN-RN`, `LPN`),
  week number, and module set (M01…), so Bed 1 can run a Week-4
  sepsis encounter while Bed 2 runs a Week-6 peds encounter.

After the room launches, each Per-Patient Console now renders a
**three-cell QR card** (Chat / EHR / Device stations) keyed to that
bed's `join_code`, identical in pattern to the v6 ops view but
scoped to one encounter. Stations scan once; the join code
authenticates them for *this* encounter only — no cross-bed
contamination.

This is what closes the user's stated requirement: *"each character
in the multi patient can have the same ability assign and operate
and instructor has the same level of control as they do on the
single with each character on the encounter page."*

## 2. Structure

**Files touched:**
- `portal/templates/control.html` — wizard step 4r (room mode) now
  exposes `modulesForRoom` + `programsForRoom` on `window.MEDSIM2`,
  plus `roleGroup` + `safetyClass` on `personasForRoom`.
- `portal/static/control.js` — `renderRoomEncounterRows` extended
  to render the per-row Scenario / Characters / Curriculum tab
  strip and drawers; `submitRoom` reads the per-row state and
  ships it inside each encounter object.
- `portal/static/control.css` — `.encounter-row-tabs`,
  `.row-tab[-count]`, `.characters-drawer`, `.curriculum-drawer`,
  `.row-persona-grid`, `.row-module-grid`, `.curriculum-row`.
- `portal/templates/encounter_console.html` — adds `card-network`
  with three `<img src="/api/qr.svg?data=…">` cells and a copyable
  URL under each.
- `portal/static/encounter_console.css` — `.qr-grid`, `.qr-cell`,
  `.qr-label`, `.qr-img`, `.qr-url`; mobile breakpoint collapses
  to one column.
- `portal/server.py` — `portal_room_encounter_console` adds
  `"base_url"` to the template context (re-uses the existing
  `_base_url_for_qr` helper).

**No new modules.** No schema migration. No new public dataclass
fields — `Encounter.selected_personas`, `selected_modules`,
`program_id`, and `week` already existed; the wizard simply now
*populates them per row* instead of broadcasting a single set.

## 3. Uses

### 3.1 Instructor flow

1. Wizard Step 0 → choose **Room of N**.
2. Step 4r — for each row:
   - **Scenario tab** (default open) — pick `scenario_name`,
     `patient_persona_id`, `ehr_id`, `chart_mode`, label.
   - **Characters tab** (collapsed) — opens a checkbox grid of
     the 24 personas (label + role group + safety class). The
     primary patient persona is always counted, even when its
     checkbox is hidden in the row.
   - **Curriculum tab** (collapsed) — program `<select>` (defaults
     to wizard-wide program), week `<input type=number>` (defaults
     to wizard-wide week), and a module-checkbox grid (initialized
     from wizard-wide modules).
3. Tab badges show live counts (`Characters · 3`, `Curriculum · 2`).
4. Submit → each encounter object now ships its own `personas`,
   `modules`, `program_id`, `week`.

### 3.2 Console QR card

After room launch, the instructor opens `/portal/room/encounter/{id}`
and sees the **📱 Connection · QR codes** card alongside telemetry,
ECG, devices, transcript, voice, etc. Each QR cell embeds an
`/api/qr.svg?data=…` SVG of the *bed-scoped* join URL:

- `{base_url}/join?code={join_code}` — chat station
- `{base_url}/ehr/join?code={join_code}` — EHR station
- `{base_url}/device/join?code={join_code}` — device station

Mobile devices scan once; the join code is the same one that
gates all `/api/encounter/{id}/…` calls for this bed.

## 4. Functions (exported API surface)

No new public functions. M31 is a wiring / template / JS-glue
module — it leans on these already-shipped surfaces:

| Symbol | Where | Purpose |
|--------|-------|---------|
| `POST /api/room/start` | `portal/server.py` | Already accepts `personas`, `modules`, `program_id`, `week` per encounter; wizard now sends them. |
| `Encounter.selected_personas` | `portal/control_session.py` | List of persona IDs (already existed; populated per row). |
| `Encounter.selected_modules` | `portal/control_session.py` | List of module IDs (already existed; populated per row). |
| `Encounter.program_id` / `.week` | `portal/control_session.py` | Curriculum context (already existed; populated per row). |
| `GET /api/qr.svg?data=…` | `portal/server.py` (M5-era) | Returns an SVG QR encoding the URL; called by each `<img>` in the console QR card. |
| `_base_url_for_qr(request)` | `portal/server.py` | Builds the `scheme://host[:port]` prefix that the template embeds in each station URL. |

## 5. Limitations

- **Wizard does not validate** that a row's primary patient persona
  is in the row's character multi-select. The submit handler
  *unions* the primary persona into the list, so the instructor
  cannot accidentally launch a bed without its patient.
- **The Curriculum drawer's week field is freeform.** Bed-level
  weeks outside the program's published range are accepted silently
  — they only act as labels in the cohort debrief facet header.
- **QR cells are static SVG.** Refreshing the encounter console
  re-issues the same join URLs — the join code does not rotate
  per scan, matching the v6 ops-view threat model (single-instructor,
  LAN-only, classroom session). A future module could rotate codes
  on a per-station first-scan if cross-room contamination becomes
  a real risk.
- **Module list shown per row is the global library.** There is no
  filter "modules a Week-6 BSN student would actually see" — the
  instructor is trusted to pick coherently. Future M32 could
  intersect the row's program/week with the module catalog.
- **QR images do not include a fallback short code or numeric
  pairing PIN.** If the camera can't read the QR, the instructor
  must type the URL from the `<code class="qr-url">` under each cell.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_wizard_depth_and_qr.py::test_encounter_console_renders_qr_card` | `card-network` + 3 station labels + `/join?code=…`, `/ehr/join?code=…`, `/device/join?code=…` patterns + join code echo in HTML | PASS | 2026-05-27 |
| `tests/v7/test_wizard_depth_and_qr.py::test_wizard_exposes_modules_and_programs_to_js` | `modulesForRoom` + `programsForRoom` + `roleGroup` appear in `/portal/control` HTML | PASS | 2026-05-27 |
| `tests/v7/test_wizard_depth_and_qr.py::test_room_start_carries_per_row_personas_modules_program_week` | Two encounters posted with distinct personas/modules/program/week → `room.encounters` carries per-bed values + no bleed | PASS | 2026-05-27 |
| `tests/v7/test_wizard_depth_and_qr.py::test_qr_svg_route_responds` | `/api/qr.svg?data=hello+world` returns 200 + `image/svg` + `<svg>` body | PASS | 2026-05-27 |
| **Full v7 suite** | **200 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | QR endpoint param fix (`text=` → `data=`) in template + test to match existing `/api/qr.svg` route signature | `portal/templates/encounter_console.html`, `tests/v7/test_wizard_depth_and_qr.py` |
| 2026-05-27 | claude-code | Per-row Characters + Curriculum drawers in wizard step 4r | `portal/templates/control.html`, `portal/static/control.js`, `portal/static/control.css` |
| 2026-05-27 | claude-code | QR-codes card on Per-Patient Console (chat / EHR / device) | `portal/templates/encounter_console.html`, `portal/static/encounter_console.css`, `portal/server.py` (template context) |
| 2026-05-27 | claude-code | 4 acceptance tests for both halves of M31 | `tests/v7/test_wizard_depth_and_qr.py` |

## 8. Open questions / known issues

- **The Characters drawer multi-select uses the full 24-persona
  library.** When the row's primary persona is e.g. a pediatric
  patient, the drawer still shows e.g. the CCU-RN — there is no
  contextual filter. The wizard's Step-4 (single-patient) filters
  apply only to the wizard-wide list, not the per-row drawer. This
  is intentional for v7.0 (the instructor knows the cast they want)
  but a future M32 could mirror Step-4's `roleGroup` + `safetyClass`
  filters inside the row drawer.
- **The QR card refresh is page-load only.** If a join code is
  rotated mid-session (future feature), the instructor must
  hard-refresh the console to see the new QR. The existing 2-s
  poll in `encounter_console.js` does not touch the QR card.
- **Mobile collapse rule** uses `@media (max-width: 700px)` —
  matches the v6 ops view; verify if the target classroom tablet
  is a 10" Android (likely fine) vs. a 7" model (cells stack early,
  which is acceptable).
- **No telemetry on the QR card.** Per M30 design we kept the
  cards independent — telemetry has its own card, devices have
  theirs, network has its own. If we ever consolidate, the QR
  card should remain visible (instructor's primary "how do
  students get in" landmark).

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`
(uses the project's installed pandoc / wkhtmltopdf pipeline). The
Markdown is the source of truth — regenerate the PDF on each
material change.*
