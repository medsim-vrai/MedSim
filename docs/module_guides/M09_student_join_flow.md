# M9 — Student join flow (room QR → roster → encounter → station)

**Phase:** 5 — Roster
**Status:** DONE (2026-05-26)
**Blocked by:** M6, M8
**Blocks:** M10, M20
**Estimated effort:** 2 days · **Actual:** 0.5 day

---

## 1. Purpose

The student-side journey: scan a room QR → land on
`/portal/students/join?code=ROOM_CODE` → pick a name (from the
operator-loaded roster) or type a free-form display name → see the
room's encounter cards → tap one → join an encounter's chat
station as the next student. The encounter's patient persona is the
conversational partner (room-mode encounters have exactly one).

This is the missing wire between the M8 student-roster persistence
layer and the existing v6 chat-station UI. After M9, the operator
flow stays in the v7 dashboard, students join through M9's
public page, and both meet at the existing v6
`/station/{join_code}/{station_id}` chat UI.

## 2. Structure

**New files:**
- `portal/templates/student_join.html` — Public landing page,
  extends nothing (no operator nav). Three states: error,
  step-1-name, step-2-encounter.
- `portal/static/student_join.css` — Mobile-first; large tap
  targets; roster grid + encounter grid responsive.
- `portal/static/student_join.js` — Roster pick / free-form name
  capture; encounter card POSTs `/portal/students/register` with
  the form fields; redirects on success.

**Files touched:**
- `portal/server.py` — adds two routes under "V7 — Student join
  flow (M9)":
  - `GET  /portal/students/join?code=ROOM_CODE` (public)
  - `POST /portal/students/register` (public)
  And a helper `_room_by_code(room_code)` that resolves a room
  by its operator-displayed code (case-insensitive).

## 3. Uses

- The M5 charge-nurse dashboard shows the room code; the operator
  reads it aloud, or displays the QR (M21 LAN test step). Students
  scan/type the code.
- Students arrive at `/portal/students/join?code=<code>` →
  see encounter cards + (optionally) the pre-loaded roster.
- They tap an encounter → JS posts `/portal/students/register`:
  - `room_code`, `encounter_id`, `display_name` (required for new),
    `existing_student_id` (optional — reattach).
- The handler:
  1. `room = _room_by_code(...)` — 404 if unknown
  2. `room.add_student(display_name)` OR reattach via
     `existing_student_id`.
  3. `room.assign_student(student_id, encounter_id)` → M8 writes
     through to DB.
  4. `enc.add_station(station_id)` with `enc.patient_persona_id`.
  5. Returns `{redirect_url: "/station/{enc.join_code}/{station_id}"}`.
- The JS redirects → the existing v6 chat-station UI loads with
  the patient persona ready to chat.

## 4. Functions (exported API surface)

### HTTP routes

| Method | Path | Auth | Returns |
|--------|------|------|---------|
| GET  | `/portal/students/join?code=ROOM_CODE` | public | HTML template (error / step-1 / step-2 states) |
| POST | `/portal/students/register` | public (room_code is the access token) | `{ok, student_id, display_name, encounter_id, station_id, redirect_url}` |

### POST body

| Field | Required | Notes |
|-------|----------|-------|
| `room_code` | yes | Case-insensitive; uppercased server-side. |
| `encounter_id` | yes | Must be an id in `room.encounters`. |
| `display_name` | yes (for new students) | Free-form. |
| `existing_student_id` | no | Reattach to an existing Student row (no duplicate). |

### Errors

| Status | When |
|--------|------|
| 400 | `display_name` blank AND no `existing_student_id`. |
| 404 | Unknown `room_code`, unknown `encounter_id`, unknown `existing_student_id`. |
| 409 | Encounter has no patient persona configured. |

### Internal helpers

| Symbol | Purpose |
|--------|---------|
| `_room_by_code(room_code)` | Resolve a room by operator-displayed code. Case-insensitive match against the active room. Returns None on miss. |

## 5. Limitations

- **One active room at a time.** Matches the single-instructor model.
  If the operator ends room A and starts room B with a colliding
  6-char code, students scanning A's stale code will see B's
  content. The 6-char alphabet has ~387M codes — collision is
  improbable but possible. M21 LAN test should verify.
- **No persona pick.** Room-mode encounters have one
  `patient_persona_id`; the student doesn't choose. In single-
  patient mode (rooms-of-1 created by the v6 wizard branch), the
  encounter may carry multiple `selected_personas` — the M9
  handler falls back to the first one when `patient_persona_id` is
  None. For multi-persona conversations the v6 `/join?code=` flow
  is still the right path.
- **Roster reattach by `existing_student_id` only.** No "match by
  display_name" — that would silently re-bind a student to a stale
  row. The roster-card UI passes the student_id explicitly when
  the student taps a pre-loaded name.
- **No heartbeat yet.** M8's `touch_student` helper exists but no
  route calls it. M16's WebSocket transport will add a heartbeat
  channel.
- **No instructor override.** A student picks themselves; the
  operator can't force-rebind without going through the M4
  `/api/encounter/{id}/assign_students` route (which doesn't yet
  write through to the DB — see M8 known issues §8).
- **Cookies not used.** Each tab is a fresh student. A future
  v7.1 may set a student session cookie so a refresh or short-
  duration disconnect doesn't require re-entering the name. For
  now, the chat station's existing `station_id` in the URL
  persists the identity.

## 6. Test status

### Automated (`tests/v7/test_student_*.py`)

| Test file | Cases | Status | Last run |
|-----------|-------|--------|----------|
| `test_student_register_then_pick_encounter.py` | 5 — happy path register+assign+station+redirect, reattach to existing roster entry, GET page renders room + roster, blank name 400s, unknown encounter 404s. | PASS | 2026-05-26 |
| `test_student_join_url_handles_unknown_room_code.py` | 6 — no code → error form, unknown code → error, stale code after room swap, lowercase code, POST 404s on unknown code, POST 404s with no active room. | PASS | 2026-05-26 |

11/11 PASS. **Full v7 suite: 54/54 passing** (up from 43). **Full v6
regression on v7: 165 passed**, same 6 env-flaky pre-existing
failures, **0 v7 regressions**.

### Manual (browser preview — 2026-05-26)

| Flow | Result |
|------|--------|
| `GET /portal/students/join?code=<code>` after starting a 2-bed room | PASS — room code visible, no operator chrome; step 1 (name) shown; step 2 (encounters) hidden until name is entered. |
| Type name + blur | PASS — step 2 reveals with "Welcome, Alice Pham. Pick a bed to start." status. |
| Tap Bed 1 card | PASS — POST register, redirect to `/station/6NDBQF/<sid>` with v6 station UI loaded; persona = encounter's `patient_persona_id`. |
| Operator dashboard polls after join | PASS — Bed 1 chat_stations: 0→1, students: 0→1; Bed 2 untouched (encounter scoping holds). |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Two new public routes (`GET /portal/students/join`, `POST /portal/students/register`) + `_room_by_code` helper. New public template + CSS + JS for the student-side join page. 11 acceptance tests across 2 files. Live browser verification of the operator→student handshake. | `portal/server.py`, `portal/templates/student_join.html`, `portal/static/student_join.{css,js}`, `tests/v7/test_student_register_then_pick_encounter.py`, `tests/v7/test_student_join_url_handles_unknown_room_code.py` |

## 8. Open questions / known issues

- The M4 dashboard's `/api/encounter/{id}/assign_students` route
  still mutates state directly (not through `room.assign_student`),
  so DB write-through doesn't fire on that path. M9 doesn't fix
  this — its own register flow uses the correct helper. Migrating
  M4's route is a small cleanup; the contract for M9 is met.
- No "back" button on the student page after picking an encounter.
  If the student taps the wrong bed, they'd have to ask the
  instructor to reassign. Adding a back affordance is a v7.1 UX
  polish.
- The page doesn't surface "this room is frozen" — a frozen room
  still lets students join (they'll just see a paused chat
  station). Whether to block joins during freeze is a policy
  question; M5 dashboard treats freeze as "everyone hold," so
  blocking joins is the natural extension. Defer until M21 LAN
  feedback clarifies the operator intent.
- QR code generation for the room code itself is M5 follow-up
  (the dashboard currently just displays the code in text). M21
  LAN test exercises a real QR scan; if a tap-friendly QR is
  missing, surface it on the dashboard then.
- The 6-char `room_code` alphabet excludes visually similar chars
  (0, O, 1, I, L), giving ~387M codes — collisions are improbable
  but possible. M19 capacity hardening should add a uniqueness
  check across recent ended rooms if collisions ever materialize.
