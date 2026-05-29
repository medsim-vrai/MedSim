# M36 — Nursing Station QR + instructor launch button

**Phase:** Phase 7 follow-on (post-M35, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M5 (Multi-Patient Control dashboard), M22 (Per-Patient Console), M27 (Nursing Station student role), M31 (per-encounter QR card)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M35:

> "On the control room or encounter control, each should have a QR
> code setup to launch the nursing station in a new computer or
> tablet, and a button to open the nurses station from the control
> page by opening a new window to host the nursing station for the
> instructor."

Two launch points for the Nursing Station from instructor surfaces:

1. **QR code** — for a separate tablet/laptop to scan and host the
   Nursing Station view on a different device. Encodes the room-
   level URL `/portal/students/join?code={room_code}` (where the
   scanner picks the Nursing Station role on the join form).
2. **Open Nursing Station button** — opens the Nursing Station in a
   new tab on the instructor's current machine. Auto-creates (or
   reuses) a nurse-station student named *"Instructor (Nursing
   Station)"* behind the scenes — same pattern as M34's EHR launch.

Both launch points appear on:

- **Multi-Patient Control dashboard** (`/portal/room`) — as a
  dedicated 🩺 Nursing Station panel between the top bar and the
  encounter grid.
- **Per-Patient Console** (`/portal/room/encounter/{id}`) — as a
  4th cell in the QR-codes card, alongside Chat / EHR / Device
  station cells.

The Nursing Station is room-scoped (supervises every bed), so its
QR encodes the **room code**, not any encounter's join code. The
QR card's footer copy on each console explains this so the
operator doesn't confuse the two codes.

## 2. Structure

**Files touched:**
- `portal/server.py`:
  - `portal_room` (route `GET /portal/room`) now fetches the active
    room via `control_room.get_active_room()` and passes a
    `room` dict (`{room_code, room_id, label}`) + `base_url` to the
    template context. Both are `None`-safe — the template renders
    the nurse-station panel only when `room` is truthy.
  - New route `GET /portal/control/launch_nurse_station` —
    instructor convenience launcher. Looks up an existing
    nurse_station student with `display_name == "Instructor
    (Nursing Station)"`; if found, redirects to its sid URL;
    otherwise creates one via `room.add_student(name,
    role="nurse_station")` and redirects there. Bounces to
    `/portal/room` (303) when no room is active.
  - New module-level constant `_INSTRUCTOR_NURSE_STATION_NAME =
    "Instructor (Nursing Station)"`.
- `portal/templates/control_room.html`: new `<section
  class="nurse-station-launch">` between the empty-state block and
  the encounter grid; renders only inside `{% if room %}`.
- `portal/templates/encounter_console.html`: new 4th `<div
  class="qr-cell qr-cell-nurse">` in the QR-codes card, plus the
  footer copy clarifying that the Nursing Station scans the room
  code (not the encounter's join code).
- `portal/static/control_room.css`: new `.nurse-station-launch`,
  `.nurse-station-launch-btn`, `.nurse-station-launch-qr`,
  `.nurse-station-qr-img`, `.nurse-station-qr-url` styles + mobile
  breakpoint.
- `portal/static/encounter_console.css`: `.qr-grid` bumped to
  `repeat(4, 1fr)`, added a midpoint breakpoint (≤1000 px → 2
  columns) so 4 cells still collapse cleanly. New
  `.qr-cell.qr-cell-nurse` styling (green tint to distinguish from
  the three encounter-scoped cells).

**No schema migration. No new dataclass field.** The instructor
nurse-station student is just a regular `Student` row with
`role="nurse_station"` and a specific `display_name`.

## 3. Uses

### 3.1 QR-on-separate-device flow

1. Instructor on `/portal/room` (or any Per-Patient Console) sees
   the 🩺 Nursing Station QR.
2. A separate tablet/laptop scans the QR.
3. Browser opens `{base_url}/portal/students/join?code={room_code}`
   — the same public landing page the M27 register_nurse flow uses.
4. Scanner picks the **Nursing Station** role on the join form,
   types a display name, submits → `POST
   /portal/students/register_nurse` → 303 to
   `/portal/students/nurse_station?sid=<student_id>`.
5. The tablet now shows the supervisor view (multi-bed telemetry,
   alarms, intercom).

### 3.2 Instructor launch flow (button)

1. Instructor clicks **🩺 Open Nursing Station (new window)**.
2. Browser opens `/portal/control/launch_nurse_station` in a new
   tab (`target="_blank" rel="noopener"`).
3. Server resolves the active room, searches the roster for a
   nurse_station student named *"Instructor (Nursing Station)"*.
   - First call: creates one via `room.add_student(name,
     role="nurse_station")`.
   - Subsequent calls: reuses the existing seat — no duplicate
     entries in the roster.
4. 303 redirect to `/portal/students/nurse_station?sid=<sid>`.
5. Instructor lands on the supervisor view without typing
   anything.

### 3.3 Side-by-side workflow

`target="_blank"` means the Nursing Station opens in its own
browser tab. The instructor can drag it to a second monitor and
keep the Multi-Patient Control dashboard (or a Per-Patient
Console) on the primary monitor. The 🩺 inline button on each
Per-Patient Console gives a discovery path for instructors who
arrive at the QR card and want to skip the QR step entirely.

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `GET /portal/control/launch_nurse_station` | `portal/server.py` | 303 → `/portal/students/nurse_station?sid=…`. Creates the instructor seat on first call; reuses on subsequent calls. Bounces to `/portal/room` if no room is active. |
| `_INSTRUCTOR_NURSE_STATION_NAME` | `portal/server.py` | Sentinel display name (`"Instructor (Nursing Station)"`) used to identify the instructor seat for reuse lookups. |

## 5. Limitations

- **Roster cap counts the instructor seat.** Adding the instructor
  nurse-station seat consumes one of the 24 student station slots
  (M19 cap). If a classroom already has 24 students plus a 25th
  instructor click on the button, the route returns 409. Acceptable
  — classroom capacity is the limit; the instructor seat is small
  next to it. We could exempt instructor seats from the cap in a
  future M37 if the constraint bites in practice.
- **The launcher does not honor a custom display name.** Every
  instructor click ends up at the same *"Instructor (Nursing
  Station)"* seat. If two instructors share a session, they share
  the seat (last writer wins on any text the seat sends back).
  Out of scope today; matches the M34 EHR launcher's
  *"Control room (instructor)"* single-seat pattern.
- **The QR points at the public role-picker page.** The scanner
  must still pick "Nursing Station" from the role list. A `?role=
  nurse_station` URL hint that pre-selected the role on the join
  form would shave one click off; left for a future M37.
- **The Per-Patient Console's 4th QR cell adds visual width.** On
  narrow screens the new midpoint breakpoint at 1000 px collapses
  the 4-cell grid to 2-cell. Verified in tests but worth eyeing on
  a real 8-inch tablet.
- **The dashboard panel only appears when a room is active.** The
  empty-state CTA is unchanged. If an instructor wants to preview
  the Nursing Station before starting a room, there's no path —
  acceptable, the nursing station is meaningless without
  encounters.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_nurse_station_launch.py::test_launch_nurse_station_creates_instructor_student_and_redirects` | First call creates instructor seat + 303 to sid URL | PASS | 2026-05-27 |
| `…::test_launch_nurse_station_reuses_existing_instructor_seat` | Repeat calls return the same sid (no roster bloat) | PASS | 2026-05-27 |
| `…::test_launch_nurse_station_no_room_redirects_to_dashboard` | No active room → 303 back to `/portal/room` | PASS | 2026-05-27 |
| `…::test_launch_nurse_station_redirect_target_actually_serves` | The sid URL serves 200 (not a dead link) | PASS | 2026-05-27 |
| `…::test_dashboard_renders_nurse_station_panel_when_room_active` | `/portal/room` carries `nurse-station-launch`, "Open Nursing Station" copy, QR data, plain URL, launcher href, `target=_blank` | PASS | 2026-05-27 |
| `…::test_dashboard_omits_nurse_station_panel_when_no_room` | No active room → panel does not render | PASS | 2026-05-27 |
| `…::test_encounter_console_renders_nurse_station_qr_cell` | Per-Patient Console QR card has `.qr-cell-nurse` with room-coded QR + "Open here" launcher link | PASS | 2026-05-27 |
| `…::test_encounter_console_help_text_clarifies_room_vs_join_code` | Footer copy mentions "Nursing Station uses the room code" + the actual code | PASS | 2026-05-27 |
| **Full v7 suite** | **239 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M36 implementation: new `/portal/control/launch_nurse_station` route; dashboard panel + per-encounter QR cell + CSS; 8 new tests | `portal/server.py`, `portal/templates/control_room.html`, `portal/templates/encounter_console.html`, `portal/static/control_room.css`, `portal/static/encounter_console.css`, `tests/v7/test_nurse_station_launch.py` (new) |

## 8. Open questions / known issues

- **Pre-select Nursing Station role via URL hint.** The QR could
  point at `/portal/students/join?code={room}&role=nurse_station`
  and `student_join.js` could auto-check the nurse-station radio.
  Small UX win for tablet scanners. Tracked for M37.
- **Display name customization for the instructor seat.** Currently
  the launcher always lands on the same *"Instructor (Nursing
  Station)"* seat. If a classroom has two co-instructors and they
  want to type comments into the supervisor intercom log
  separately, they'd want distinct seats. Out of scope today; the
  M28 intercom is currently one-way nurse → bedside so the issue
  is theoretical.
- **The QR is room-scoped but lives on per-encounter consoles.**
  An instructor scanning four different encounter consoles each
  shows the same nursing-station QR. That's correct (one nurse
  station per room), but the redundancy could confuse someone who
  thinks each console scans a *different* nurse station. The
  footer copy clarifies this; if confusion persists in LAN test,
  consolidate to dashboard-only and remove the per-encounter cell.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
