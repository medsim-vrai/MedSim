# Medsim_v7 LAN acceptance test (M21 release gate)

The v7 full-build release gate is **a manual LAN test on real
hardware** — verifying that the multi-patient features (M0–M19)
behave correctly across genuine wifi latency, real iPad / Android
browsers, and a real classroom shift's worth of concurrent load.
This file is the test protocol.

Run this AFTER the automated v7 suite is green (which it is — 132
v7-only acceptance tests + 243 in the full suite all pass, with
the 6 pre-existing env-flaky failures matching the v6 baseline
exactly).

---

## 0. Pre-flight

**Hardware:**
- 1 instructor laptop (the one running `run_portal.py` with
  `MEDSIM_HOST=0.0.0.0` for LAN binding).
- Up to 8 student devices (mix of iPads + Chromebooks +
  phones is fine — any browser that ran v6 fine runs v7 fine).
- Optional: a tablet for the observer-seat (M18) — a second
  instructor / preceptor.

**Software:**
- `python3 -m pytest tests/ -q` → 132+ v7 + 243 total passed,
  6 env-flaky (matches v6).
- `./launchers/mac/Start Portal (iPad mode).command` (or the
  Windows equivalent) — confirm the LAN URL is shown on the
  splash.

---

## 1. Test matrix

| Test | Tablets | Encounters | Bar |
|------|---------|------------|-----|
| **T1** Smoke — 2 tablets, 2 encounters | 2 | 2 | Each chats with their patient, each writes a note + vitals, freeze-all locks both within ≤ 1 s. |
| **T2** Scale-up — 4 tablets, 3 encounters | 4 | 3 (one shared with 2 tablets) | Per-encounter scoping holds; the shared bed shows both students' edits; private bed isolated. |
| **T3** Full classroom — 8 tablets, 4 encounters | 8 | 4 (mix of shared + private_clone) | Capacity bar in dashboard never exceeds 8/24 stations; scene_broadcast hits all 4 charts within ≤ 5 s; cohort debrief after end_room renders the right number of facets (one per encounter + per clone). |
| **T4** Observer seat | 8 + 1 observer | same as T3 | Observer can see dashboard + debrief; observer's attempts to freeze / end / inject scene → 403 + "Observer is read-only" toast. |
| **T5** Capacity edge — try 11 encounters | n/a | 11 | Wizard finalize → 409 + clear "Room capacity reached (10 max)" message. |

---

## 2. Per-test checklist

For each row in the matrix, verify:

- [ ] **Operator wizard finalize** — wizard's Room-of-N branch (M6)
      accepts the encounter rows; the redirect lands on
      `/portal/room` with the right N cards rendered.
- [ ] **Student join** — students scan the room QR (or open the URL
      typed); the join page renders the room's encounters and
      pre-loaded roster (if any); picking a name + bed redirects
      to the v6 chat-station URL.
- [ ] **Chat scoping** — turns on bed A do not appear on bed B.
- [ ] **EHR scoping** — notes / vitals / orders on bed A do not
      appear on bed B.
- [ ] **Freeze All ≤ 1 s** — operator click → stations show paused
      state within ≤ 1 s (M16 WebSocket push handles this; the
      poll fallback would be 2 s).
- [ ] **Scene inject vitals.drop ≤ 5 s** — operator clicks
      "Inject scene → vitals.drop" → bed A's EHR chart_event log
      shows the new vitals row within ≤ 5 s.
- [ ] **Scene broadcast** — scene targeted at "all" hits every
      encounter; encounters not targeted stay clean.
- [ ] **End room → cohort debrief saves** — operator clicks End
      → cohort debrief is saved (visible at
      `/portal/cohort-debriefs`) AND the dashboard's Cohort
      Debrief button (M5 post-end state) navigates to the
      rendered debrief.
- [ ] **PEARLS tabs render** — Reactions / Description / Analysis
      / Application / Per-encounter / Summary all show; per-
      encounter tab lists every encounter as a collapsible facet.
- [ ] **Print-to-PDF** — browser Print produces a paginated PDF
      with every panel visible + every facet expanded.

---

## 3. Edge cases (T5 + spot-checks)

- [ ] **Stale room code on a student tab** — operator ends room A,
      starts room B with new code. A student's old tab pointing
      at `code=<A>` → error page with "Room not found", not a
      leak into B.
- [ ] **Private-clone reuse** — operator finalizes 1 bed in
      private-clone mode. 3 students each join the same bed →
      3 clones spawn. Charting on Alice's clone doesn't appear on
      Bob's.
- [ ] **Activity catalog** — wizard Step 4r picks the
      `builtin_msurg_dka` activity → the row's label + persona +
      module list auto-fill from the catalog; encounter at start
      carries the activity_id.
- [ ] **Cost cap** — set `voice_char_cap=200` on a 4-bed room;
      run 3 voice turns averaging 80 chars each → 4th turn 503s
      with `{"fallback": true}`; browser drops to SpeechSynthesis;
      bedside chat continues without interruption.
- [ ] **Observer attempts a mutator** — observer dashboard's
      Freeze All button (M5) is still visible (no UI gating yet)
      but the POST returns 403 + Observer is read-only message.

---

## 4. Performance targets

- Dashboard poll → /api/room/state under typical LAN load: < 50 ms
  P95 server response.
- WebSocket push freeze_all → bedside reaction: < 500 ms.
- Scene inject → chart_event row durable + readable: < 5 s.
- Cohort debrief save (10-encounter room): < 2 s total.

---

## 5. Sign-off

Fill in the matrix below as each test passes (or note the failure
and link to the bug). Sign off both sides — operator + at least
one student — before marking M21 / the v7 full build complete.

| Test | Date | Operator | Notes |
|------|------|----------|-------|
| T1 (2×2) | __________ | __________ | |
| T2 (4×3) | __________ | __________ | |
| T3 (8×4) | __________ | __________ | |
| T4 (observer) | __________ | __________ | |
| T5 (capacity 11) | __________ | __________ | |

**M21 — RELEASE GATE PASSED when every row in §5 is signed off
AND the automated suite is green.**
