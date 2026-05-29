# M17 + M18 + M19 — Cost caps, Observer seat, Capacity hardening

**Phase:** 11–13
**Status:** DONE (2026-05-26)
**Combined guide** — three smaller modules shipped in one pass for
brevity. Each section below is the equivalent of an individual
M-guide.

---

## M17 — Per-encounter cost caps

**Goal:** configurable per-room caps on Haiku turns/minute and
ElevenLabs character budget; graceful fallback on overrun.

**Files:**
- `portal/budgets.py` (new) — `RoomBudgetTracker`, `Decision`,
  `_RateWindow` sliding-60s tracker. Returns `Decision(allow,
  fallback, reason, remaining)` per check.
- `portal/control_room.py` — `ControlRoom.budget` property lazily
  builds a `RoomBudgetTracker` and keeps its caps in sync with the
  room's `haiku_rate_cap` / `voice_char_cap` fields.
- `portal/server.py` — `GET /api/room/budget` (usage snapshot) and
  `POST /api/room/budget` (set caps).

**Contract on overrun:**
- Haiku rate cap exceeded → `fallback='refuse'` — caller refuses
  the turn with a "(rate-limited)" notice.
- Voice char cap exceeded → `fallback='browser_tts'` — caller emits
  a 503 + `{"fallback": true}` so the browser switches to
  SpeechSynthesis.

**Wire-up to v6 LLM/TTS call sites is deferred** — the contract is
in place; integration with `runtime.py` and `voices.py` is a
follow-up so M21 LAN-test feedback can shape the latency budget.
The data layer is fully testable and tested.

**Tests:** `tests/v7/test_voice_budget_falls_back_to_browser_tts_on_overrun.py`
(5 cases), `test_haiku_rate_cap_throttles_turns_when_exceeded.py`
(5 cases). 10/10 PASS.

---

## M18 — Observer instructor seat (read-only)

**Goal:** a TA / preceptor login that can view every page but
can't fire any mutator.

**Files:**
- `portal/auth.py` — adds `role` parameter to
  `issue_session_token(vault, role='instructor'|'observer')`,
  `session_role(token)` helper, `require_instructor` dependency
  that gates state-mutating routes.
- `portal/server.py` — `/login` now accepts a `role` form field
  (defaults to 'instructor'). Twelve v7 mutating routes swapped
  from `auth.require_vault` to `auth.require_instructor`:
  - `/api/room/start`, `freeze_all`, `resume_all`, `end`,
    `scene_broadcast`
  - `/api/encounter/{id}/scene`, `assign_students`
  - `/api/activities` (POST), PATCH/DELETE `/api/activities/{id}`
  - `/api/room/budget` (POST)
  - `/api/debrief/cohort/{room_id}/notes`

**Read paths (GET /api/room/state, GET /api/activities, debrief
views, etc.) stay on require_vault** — observers can read
everything.

**Tests:** `tests/v7/test_observer_seat.py` — 5 cases (cannot freeze,
sees dashboard, every v7 mutator rejected for observer, instructor
default keeps mutators open, session_role helper default). 5/5
PASS.

**Out of scope:** v6's existing routes (login, character CRUD,
scenarios CRUD) are NOT gated — observers can still touch the v6
library. Bigger surface area, deferred to a future pass when the
observer-seat UX is validated on real LAN testing.

---

## M19 — Capacity hardening

**Goal:** v1 caps — 10 concurrent encounters per room, 24 student
stations. Enforce at the data + route layer; surface on the
dashboard.

**Files:**
- `portal/control_room.py` — module constants
  `MAX_ENCOUNTERS_PER_ROOM = 10`, `MAX_STUDENT_STATIONS_PER_ROOM
  = 24`. `CapacityExceeded` exception. `_count_student_stations`
  helper. `ControlRoom.add_encounter` raises on overflow.
- `portal/server.py`:
  - `/api/room/start` returns 409 if N > 10 encounters requested.
  - `/portal/students/register` returns 409 if station cap would
    be exceeded.
  - `/api/room/state` payload includes a new `capacity` block:
    `{encounters_used, encounters_max, student_stations_used,
    student_stations_max}` for the dashboard banner.

**Tests:** `tests/v7/test_capacity_caps.py` — 6 cases (data-layer
11th encounter blocked, station count helper, route 409 on big
finalize, capacity block in /state, 25th student rejected,
capacity bar updates live). 6/6 PASS.

---

## Combined test summary

- New v7 acceptance: **21 tests across 4 files** — 10 (M17) + 5
  (M18) + 6 (M19).
- **Full v7 suite: 132/132 passing** (up from 111 — +21).
- **Full v6 regression on v7: 243 passed**, same 6 env-flaky
  pre-existing failures, **0 v7 regressions**.

## Combined change list

| Date | Module | Files |
|------|--------|-------|
| 2026-05-26 | M17 | `portal/budgets.py` (new), `portal/control_room.py` (`budget` property), `portal/server.py` (2 routes), `tests/v7/test_voice_budget_*.py`, `tests/v7/test_haiku_rate_cap_*.py` |
| 2026-05-26 | M18 | `portal/auth.py` (role + require_instructor), `portal/server.py` (login role + swap 12 routes), `tests/v7/test_observer_seat.py` |
| 2026-05-26 | M19 | `portal/control_room.py` (constants + CapacityExceeded + station counter + add_encounter gate), `portal/server.py` (409 gates + capacity block in /state), `tests/v7/test_capacity_caps.py` |

## Known issues (combined)

- M17's wire-up to the v6 LLM call path is deferred; the data
  layer is testable today.
- M18 only gates v7 mutating routes. The v6 control/library
  surface (still on `require_vault`) is open to observers. Sweep
  that in a hygiene-pass module after M21 feedback.
- M19's 10 / 24 caps are v1 numbers; M21 LAN test will validate
  on real hardware. The constants live in `control_room` for easy
  tuning. A future per-room override field could let operators
  raise caps when they have the hardware.
