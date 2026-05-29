# M15 — Cohort debrief UI

**Phase:** 9 — Debrief
**Status:** DONE (2026-05-26)
**Blocked by:** M14
**Blocks:** none
**Estimated effort:** 2 days · **Actual:** 0.5 day

---

## 1. Purpose

Render the M14 cohort debrief JSON as an instructor-facing web page
with PEARLS-section tabs (Reactions / Description / Analysis /
Application / Per-encounter / Summary), live-editable notes +
commitments, and a Print-to-PDF affordance. Also wire
`POST /api/room/end` to **save** the cohort debrief before the
singleton is cleared, so the debrief survives the end.

## 2. Structure

**New files:**
- `portal/templates/debrief_cohort.html` — PEARLS-tabbed render of
  one cohort.
- `portal/templates/debrief_cohort_index.html` — list of every
  saved cohort.
- `portal/static/debrief_cohort.{js,css}` — tab switching,
  commitments editor, save-notes round-trip, print-friendly CSS.

**Files touched:**
- `portal/server.py`:
  - `POST /api/room/end` now calls
    `debrief_mod.build_cohort_debrief(room)` + `save_cohort(...)`
    BEFORE `end_active_room()`. Response carries
    `cohort_debrief_saved` and `cohort_debrief_url`.
  - New routes:
    - `GET /portal/debrief/cohort/{room_id}` — HTML render.
    - `GET /api/debrief/cohort/{room_id}` — JSON read.
    - `POST /api/debrief/cohort/{room_id}/notes` — save instructor
      notes + commitments.
    - `GET /portal/cohort-debriefs` — index page (path is plural,
      top-level, to avoid colliding with the v6
      `/portal/debrief/{session_id}` catch-all).

## 3. Uses

- **Operator ends a room** via M5 dashboard's End Room button →
  `/api/room/end` saves the cohort + clears singleton → response
  carries `cohort_debrief_url` for client-side redirect.
- **Operator opens a saved cohort debrief** via the M5 dashboard's
  Cohort Debrief button (when `lastKnownRoomId` is set) OR via the
  `/portal/cohort-debriefs` index.
- **Instructor edits notes + commitments live** during the
  PEARLS-led debrief → `POST .../notes` persists.
- **Print/Save-as-PDF** — browser-native print, with CSS that
  forces every PEARLS panel visible and expands every encounter
  facet.

## 4. Functions (exported API surface)

### HTTP routes

| Method | Path | Returns |
|---|---|---|
| GET | `/portal/debrief/cohort/{room_id}` | HTML cohort debrief view, 404 if not saved |
| GET | `/api/debrief/cohort/{room_id}` | JSON read of the saved cohort, 404 if not saved |
| POST | `/api/debrief/cohort/{room_id}/notes` | Save `{reactions_notes, commitments[]}` |
| GET | `/portal/cohort-debriefs` | Index page (newest first) |
| POST | `/api/room/end` (updated) | `{ok, room_id, encounter_count, cohort_debrief_saved, cohort_debrief_url}` |

### Template structure

PEARLS tabs in this order, each as a `<section class="pearls-panel">`:
1. **Reactions** — editable textarea for instructor notes.
2. **Description** — pre-built cohort facts list.
3. **Analysis** — per-encounter performance frame table + persona
   engagement ranked list.
4. **Application** — commitment editor (add / remove items live).
5. **Per-encounter** — collapsible facet panels with transcript
   preview.
6. **Summary** — room-level aggregates.

## 5. Limitations

- **No PDF export server-side.** Print is browser-driven (Ctrl+P /
  ⌘+P → Save as PDF). A server-side PDF render would need
  WeasyPrint or similar — deferred.
- **`/portal/cohort-debriefs` lives at a top-level path** (not
  `/portal/debrief/cohort`) because the v6
  `/portal/debrief/{session_id}` catch-all would have caught
  "cohort" as a session id lookup. Documented in module guide
  §8.
- **Commitments editor doesn't save automatically** — the
  instructor must click "Save notes" to persist both Reactions
  notes and the commitments list. M21 LAN test should verify
  this is intuitive.
- **No per-encounter drill-in beyond transcript preview.** The
  encounter facets show the first 50 transcript entries; longer
  runs get truncated with a "… N more entries" hint. M21
  feedback may suggest expanding this.
- **Index page is unsorted within the "saved cohorts" list beyond
  generated_at desc.** No filter by date / instructor / activity.
  Deferred until the catalog grows past a screen's worth.

## 6. Test status

`tests/v7/test_cohort_debrief_route_renders_for_ended_room.py` — 6 cases:

| Test | Status |
|------|--------|
| `test_end_room_saves_cohort_debrief` | PASS |
| `test_cohort_debrief_route_renders_for_ended_room` | PASS |
| `test_cohort_debrief_route_404s_for_unknown_room` | PASS |
| `test_cohort_debrief_json_endpoint_returns_data` | PASS |
| `test_cohort_debrief_save_notes_round_trips` | PASS |
| `test_cohort_debrief_index_renders` | PASS |

**Full v7 suite: 104/104 passing** (up from 98 — +6 M15 tests).
**Full v6 regression on v7: 215 passed**, same 6 env-flaky
pre-existing failures, **0 v7 regressions**.

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | `POST /api/room/end` now saves cohort debrief before clearing singleton (response carries `cohort_debrief_url`). 4 new routes for cohort debrief view + JSON read + notes save + index. New `debrief_cohort.html`, `debrief_cohort_index.html`, `debrief_cohort.{js,css}`. 6 acceptance tests pass. Index route at `/portal/cohort-debriefs` (plural top-level) to avoid v6 catch-all collision. | `portal/server.py`, `portal/templates/debrief_cohort.html`, `portal/templates/debrief_cohort_index.html`, `portal/static/debrief_cohort.{js,css}`, `tests/v7/test_cohort_debrief_route_renders_for_ended_room.py` |

## 8. Open questions / known issues

- **Route-collision pattern revisited.** v6's
  `/portal/debrief/{session_id}` is greedy. Future v7 modules
  that add new debrief subroutes should use a non-conflicting
  path prefix.
- **The M5 dashboard's Cohort Debrief button** points at
  `/portal/debrief/cohort/{room_id}` (correct — the GET works).
  Need to verify the M5 button is reachable AFTER end_room (M5
  preserves `lastKnownRoomId` exactly so this could work).
  Browser preview verification deferred.
- **Print CSS forces every panel visible**, which is the right
  behavior for instructor archival but bloats the printed page
  on long-running rooms. A "compact" toggle could help.
