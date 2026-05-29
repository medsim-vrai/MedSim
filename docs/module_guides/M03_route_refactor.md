# M3 — Route refactor: get_by_join_code + single-encounter routes

**Phase:** 2 — Routes
**Status:** DONE (2026-05-26)
**Blocked by:** M2
**Blocks:** M4, M5, M9
**Estimated effort:** 2 days · **Actual:** 0.5 day (M2 already wired the
v6-compat helpers correctly; M3 was largely verification + the legacy
`_active = None` reset hook + acceptance tests)

---

## 1. Purpose

Make the existing v6 route surface multi-tenant-safe. The contract:

1. The 12 student-side routes that already take a join code in the URL
   resolve to the right Encounter rather than to a global singleton —
   so two encounters can run simultaneously without state bleed.
2. The 22 instructor-side routes that call `get_active()` continue to
   work in single-patient mode (room of 1). In multi-encounter rooms
   they fail loud (M2's `get_active()` raises) rather than silently
   picking the first encounter. The strategies A/B/C from P6 §4.1 for
   refactoring these instructor-side routes will be applied
   per-route as M4 / M5 / M6 introduce the wizard's multi-encounter
   branch.
3. No new public routes (those land in M4).

## 2. Structure

This module is mostly **verification + the legacy reset hook** —
the heavy lifting was already done by M2's `control_room` shim
(`get_by_join_code` searches across all encounters; `get_active` raises
on multi-encounter rooms). M3 confirms the contract holds.

**Files touched:**
- `portal/control_session.py` — adds a `ModuleType` subclass so that
  legacy `control_session._active = None` writes (used by v6 test
  fixtures and a few operator-debug paths) propagate the reset to
  `control_room._active_room`. Without this, the v6 test fixture's
  reset would silently no-op and state would leak between tests.

**Files NOT touched in M3:**
- `portal/server.py` route handlers — the 12 join-code routes already
  work correctly via M2's `get_by_join_code` (they call
  `control_session.get_by_join_code(code)` which delegates to
  `control_room`). The 22 `get_active()` callers also already work
  correctly in single-patient mode (room of 1). Per-route A/B/C
  refactor of `get_active()` callers happens in M4/M5/M6.

## 3. Uses

- The legacy reset hook is exercised by:
  - `tests/test_voices.py:147` — `control_session._active = None`
  - `tests/test_e2e_v3.py:46` — `control_session._active = None`
  - Any future code that uses the same v6 idiom.
- The `get_by_join_code` dispatch is exercised by every route under
  `/api/station/{join}/...`, `/api/ehr/{join}/...`,
  `/api/device/{join}/...` (12 student-side routes total).

## 4. Functions (exported API surface)

No new public API. The module-class subclass is internal:

| Symbol | Where | Purpose |
|--------|-------|---------|
| `_ControlSessionModule(ModuleType)` | `control_session.py` | Module subclass with `__setattr__` that propagates `_active = None` writes to `control_room._active_room = None`. |
| `_active` (module attr) | `control_session.py` | Sentinel attribute, value `None`. Carries no state — the real singleton is `control_room._active_room`. Writes to it trigger the reset hook above. |

## 5. Limitations

- **The 22 `get_active()` callers in server.py are not refactored
  yet.** They keep working in single-patient mode because `get_active`
  returns the sole encounter of a room-of-1. In multi-encounter mode
  (M4+), each of those callers needs strategy A (operate on the room
  aggregate), B (address one encounter by id), or C (iterate every
  encounter) per P6 §4.1. The categorization belongs to M4 (when room
  mode actually exists) — doing it now is premature.
- The legacy `_active = None` interception is a v6 back-compat shim,
  not the v7 canonical reset. New v7 tests use
  `control_room._reset_for_tests()` directly, which is more explicit.
- The module-class swap (`sys.modules[__name__].__class__ = ...`) is
  set up once at import time and survives reloads. If the test runner
  reloads `control_session.py` between tests (it does not, currently),
  the class swap would still apply because the new module object's
  class is set in module-level code.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_two_encounters_two_chat_streams_independent.py` | Two encounters in one room, stations join via `get_by_join_code`, transcripts/stations do not bleed between encounters; `freeze_all`/`resume_all` reach every encounter and resume only undoes paused state. | PASS (2 cases) | 2026-05-26 |
| `tests/v7/test_two_encounters_two_ehr_charts_independent.py` | Two encounters seed two EHR sessions, write distinct chart_events; `fold()` and `events()` return only that encounter's rows; `get_by_join_code` dispatches writes to the right encounter end-to-end. | PASS (2 cases) | 2026-05-26 |
| **v6 regression** (full v6 suite on v7) | 89 v6 tests, plus 4 device_debrief + 2 voices tests that fail identically on v6 baseline today (pre-existing environmental flake from operator's vault state — not a v7 regression). | PASS modulo 6 env-dependent failures present on both v6 and v7 (124 passed, 6 failed); 0 v7-specific regressions. | 2026-05-26 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Added `_ControlSessionModule` `ModuleType` subclass to intercept legacy `_active = None` writes and propagate to `control_room._active_room`. Added 2 acceptance test files (4 cases) under `tests/v7/`. Verified v7 has zero regressions vs v6 baseline (same 6 env-dependent failures on both). | `portal/control_session.py`, `tests/v7/test_two_encounters_two_chat_streams_independent.py`, `tests/v7/test_two_encounters_two_ehr_charts_independent.py` |

## 8. Open questions / known issues

- The 6 environmental test failures (4 in `test_device_debrief.py`, 2
  in `test_voices.py`) are pre-existing on v6 too. The voices ones
  stem from the test fixtures sharing the real `~/.medsim/vault.enc`
  with the operator's machine state (which now contains an
  `ELEVENLABS_API_KEY` from earlier work). A clean fix would
  monkeypatch `credentials.VAULT_PATH` in the test fixture rather
  than relying on `HOME` env var (`VAULT_PATH` is computed at module
  import time, so HOME monkeypatch is too late). This is an
  inherited issue, not a M3 deliverable; leaving it for a later
  test-hygiene pass.
- The 22 `get_active()` callers in server.py are catalogued for
  later (line numbers: 586, 608, 902, 986, 1010, 1042, 1085, 1103,
  1136, 1193, 1324, 1591, 1605, 1887, 1936, 1964, 1984, 2014, 2074,
  and a few more depending on file version). M4 should classify each
  by strategy A/B/C as it introduces the multi-encounter API surface.
- The legacy reset hook is best-effort (the `except Exception: pass`).
  If `control_room` import fails for any reason during test teardown,
  the reset silently no-ops. This is intentional — the hook should
  never raise during teardown. Worst case, the next test's own
  fixture's `_reset_for_tests()` (if it uses the v7 API) handles it.
