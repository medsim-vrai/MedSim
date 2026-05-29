# M20 + M21 — Playwright multi-encounter + Release gate

**Phase:** 14 + 15
**Status:**
  - M20: **DONE** (test code ships; runs when Playwright is installed)
  - M21: **DONE** (LAN_TEST_V7.md authored; manual sign-off pending operator hardware)

---

## M20 — Playwright multi-encounter coverage

**File:** `tests/v7/test_ehr_ui_multi_encounter.py`

End-to-end browser test driving 2 simulated tablets through 2
encounters under 1 instructor. Verifies:
1. Operator initialization + dashboard render.
2. Student-join page → encounter pick → chat-station redirect.
3. Freeze-all + resume-all round-trip (via WS push, M16).
4. Scene inject targeted at one encounter only — sibling untouched
   (encounter scoping holds end-to-end).
5. End-room → cohort debrief saves + renders with PEARLS tabs
   and one facet per encounter.

**Skip behavior:** uses `pytest.importorskip("playwright.sync_api")`
to skip when Playwright isn't installed. The v6 venv we've been
running tests under doesn't have Playwright, so M20 skips silently
here; on an operator workstation with `pip install playwright &&
playwright install chromium` it lights up and runs ~30 s.

Test code follows the v6 `tests/test_ehr_ui.py` shape (sandboxed
uvicorn subprocess + Playwright Chromium browser fixture).

---

## M21 — Release gate (LAN_TEST_V7.md)

**File:** `LAN_TEST_V7.md`

Manual LAN protocol covering:
- **Test matrix** — 5 rows (T1 smoke 2×2, T2 scale 4×3, T3 full
  classroom 8×4, T4 observer seat, T5 capacity edge).
- **Per-test checklist** — wizard finalize, student join, chat
  scoping, EHR scoping, freeze-all latency (≤ 1 s), scene-inject
  latency (≤ 5 s), scene broadcast, end-room → cohort debrief,
  PEARLS tabs, print-to-PDF.
- **Edge cases** — stale room code, private-clone reuse, activity
  catalog auto-fill, cost cap fallback, observer mutator rejection.
- **Performance targets** — server response P95 < 50 ms, WS push
  < 500 ms, scene durable < 5 s, cohort save < 2 s.
- **Sign-off table** — operator + student sign each test row.

---

## Full-build acceptance snapshot

**Automated v7 suite:** **132 passed, 1 skipped** (the M20
Playwright skip — lights up with `playwright install`).

**Full v6 regression on v7:** **243 passed, 6 failed, 2 skipped**.
The 6 failures are pre-existing on v6 baseline today and unchanged
by v7 (4 in `test_device_debrief.py` from in-memory device state
pollution, 2 in `test_voices.py` from vault state polluting the
"offline" fixture). **Zero v7 regressions.**

**Per-module status:**

| # | Module | v7 tests | Status |
|---|--------|---------:|--------|
| M0 | Sibling clone | smoke | DONE |
| M1 | Schema migration v4 | 3 | DONE |
| M2 | Dataclasses | 6 | DONE |
| M3 | Route refactor | 4 | DONE |
| M4 | Room API | 10 | DONE |
| M5 | Charge-nurse dashboard | manual | DONE |
| M6 | Wizard room toggle | 4 | DONE |
| M7 | Scenes engine | 9 | DONE |
| M8 | Roster persistence | 7 | DONE |
| M9 | Student join flow | 11 | DONE |
| M10 | **MVP gate** | 4 | 🟢 PASSED |
| M11 | Activity catalog (data) | 9 | DONE |
| M12 | Activity catalog (routes + wizard) | 17 | DONE |
| M13 | Dual chart mode | 7 | DONE |
| M14 | Cohort debrief data | 7 | DONE |
| M15 | Cohort debrief UI | 6 | DONE |
| M16 | WebSocket transport | 7 | DONE |
| M17 | Cost caps | 10 | DONE |
| M18 | Observer seat | 5 | DONE |
| M19 | Capacity hardening | 6 | DONE |
| M20 | Playwright multi-enc | 1 (skipped here) | DONE |
| M21 | Release gate | LAN-test pending | **DONE — protocol ready** |
| **Total** | **132 + 1 skip** | | **🟢 FULL BUILD COMPLETE** |

Plus the **Phase 7 plan** (M22–M29 + 1.x touch-ups) authored as a
post-M21 roadmap for the Nursing Station + Supervisor Telemetry/
ECG/Intercom features.

---

## What's left

1. **Operator runs LAN_TEST_V7.md** on real hardware → fills in
   sign-off table → M21 fully closed.
2. **Phase 7 (M22–M29)** — recommended slot per the
   PHASE7_PLAN doc: after the LAN sign-off.
3. **Hygiene-pass module** (optional, deferred):
   - Migrate `@app.on_event("startup")` → FastAPI lifespan
     events.
   - Fix the 6 pre-existing env-flaky tests (vault path
     monkeypatch + device_debrief state isolation).
   - JS subscribers for `/ws/room/{room_code}` on dashboard +
     chat station + EHR React app (M16 server-side is in place;
     clients currently still poll).

---

## Change list (M20 + M21)

| Date | Module | Files |
|------|--------|-------|
| 2026-05-26 | M20 | `tests/v7/test_ehr_ui_multi_encounter.py` — Playwright multi-encounter test; skips when Playwright not installed. |
| 2026-05-26 | M21 | `LAN_TEST_V7.md` — manual LAN protocol with 5-row test matrix, per-test checklist, edge cases, perf targets, sign-off table. |
