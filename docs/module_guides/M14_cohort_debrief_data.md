# M14 — Cohort debrief: data aggregation (PEARLS scaffold)

**Phase:** 9 — Debrief
**Status:** DONE (2026-05-26)
**Blocked by:** M10, M12, M13
**Blocks:** M15
**Estimated effort:** 2 days · **Actual:** 0.4 day

---

## 1. Purpose

Roll up every encounter in a ControlRoom into one PEARLS-scaffolded
debrief JSON so the instructor can run a single debrief covering
the whole cohort. PEARLS (Eppich & Cheng 2015) is the standard
nursing-debrief framework: Reactions → Description → Analysis →
Application → Summary. M14 builds the data; M15 renders it.

Robust to:
- An encounter with no transcript / no chart events.
- A completely empty room (operator started + immediately ended).
- Private-clone rooms (M13) — each clone is its own facet.
- An encounter whose per-encounter `build()` throws — the error
  surfaces as a `_error` field on that facet without breaking the
  aggregate.

## 2. Structure

**Files touched:**
- `portal/debrief.py` — appends "V7 — Cohort debrief (M14)" section:
  - `build_cohort_debrief(room) -> dict`
  - `save_cohort(debrief) -> Path`
  - `load_cohort(room_id) -> dict | None`
  - `list_saved_cohorts() -> list[dict]`
  - Module constant `COHORT_DEBRIEFS_DIR = data/debriefs/cohort/`.

**No new files** — extends `portal/debrief.py`.

## 3. Uses

- **M15** will add `/portal/debrief/cohort/<room_id>` to render this
  JSON as a web page with PEARLS-section tabs.
- **`POST /api/room/end`** (a future enhancement) should call
  `build_cohort_debrief(room)` and `save_cohort(...)` BEFORE
  `end_active_room()` clears the singleton, so the room's
  in-memory state is captured. M15 will wire this.
- **Operator-driven retro debrief:** `load_cohort(room_id)` lets
  the instructor revisit any saved cohort debrief.

## 4. Functions (exported API surface)

### Cohort builder

`build_cohort_debrief(room) -> dict` — `room` is a
`control_room.ControlRoom`. Returns:

```
{
  "room_id":     "...",
  "room_code":   "ABCDEF",
  "room_label":  "...",
  "room_status": "active|frozen|ended",
  "encounters":  [<full v6 per-encounter debrief>, ...],
  "pearls": {
    "reactions":   {"prompt": "...", "notes": ""},
    "description": {"prompt": "...", "facts": [<strings>]},
    "analysis":    {
      "prompt": "...",
      "performance_frames": [
        {session_id, scenario_name, ncjmm_coverage,
         duration_seconds, turns},
        ...
      ],
      "persona_engagement_ranked": [{persona_id, turn_count}, ...]
    },
    "application": {"prompt": "...", "commitments": []},
    "summary": {
      "encounters_count", "students_count",
      "total_chat_turns", "total_chart_events",
      "total_duration_seconds",
      "avg_duration_per_encounter_seconds",
      "avg_turns_per_encounter"
    }
  },
  "_meta": {"generated_at": <ts>, "generator": "medsim7.debrief.cohort v1"}
}
```

### Persistence

- `save_cohort(debrief)` writes `data/debriefs/cohort/<room_id>.json`.
- `load_cohort(room_id)` returns the dict or None.
- `list_saved_cohorts()` returns the index (newest first) for an
  eventual cohort-debrief library page.

## 5. Limitations

- **No per-student facet rollup.** In a shared-mode encounter with
  3 students, the facet is one debrief covering all 3 (matches v6
  per-encounter behavior). To get per-student grouping, use
  private_clone mode (M13) — each clone produces its own facet.
- **`reactions.notes` and `application.commitments` are empty at
  build time** — the instructor fills them live during the debrief.
  M15 should provide UI for these.
- **Persona engagement ranking is empty when there's no chat
  activity.** M15 should hide the section in that case.
- **No PDF export.** A v7.1 enhancement.
- **Per-encounter `build()` errors are silently captured** in the
  facet's `_error` field — they don't fail the aggregate but they
  do degrade the facet's content. M15 should surface the error
  prominently when rendering.

## 6. Test status

| Test file | Cases | Status | Last run |
|-----------|-------|--------|----------|
| `test_cohort_debrief_aggregates_3_encounters.py` | 2 — 3-encounter aggregation with mixed chart activity; save/load round-trip to `data/debriefs/cohort/`. | PASS | 2026-05-26 |
| `test_cohort_debrief_includes_pearls_sections.py` | 2 — All 5 PEARLS sections present with prompts/facts/frames; persona engagement section structure intact even when empty. | PASS | 2026-05-26 |
| `test_cohort_debrief_handles_one_encounter_with_no_charting.py` | 3 — Empty encounter handled with zeroed facet; completely empty room produces valid debrief; private-clone room produces one facet per clone. | PASS | 2026-05-26 |

7/7 PASS. **Full v7 suite: 98/98 passing** (up from 91 — +7 M14
tests). **Full v6 regression on v7: 209 passed**, same 6 env-flaky
pre-existing failures, **0 v7 regressions**.

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Appended cohort-debrief section to `portal/debrief.py`: `build_cohort_debrief` + `save_cohort` + `load_cohort` + `list_saved_cohorts` + `COHORT_DEBRIEFS_DIR`. PEARLS scaffold pre-populates Description + Analysis from cohort facts; Reactions + Application empty for live fill. 7 acceptance tests across 3 files. | `portal/debrief.py`, `tests/v7/test_cohort_debrief_*.py` |

## 8. Open questions / known issues

- **No instructor-side "complete this debrief" affordance.** Once
  M15 lands, an instructor will be able to add notes to Reactions
  and commitments to Application; those edits should be saved back
  to the cohort JSON. M15 will own this.
- **`encounters[]` facet is the full v6 debrief — large payload.**
  A 6-encounter room of 8 students could produce >100 KB of JSON.
  Acceptable for current scale; if the cohort grows, paginate or
  add a "summary mode" toggle.
- **Private_clone aggregation:** all clones share `cloned_from_id`.
  M15 should visually group clones under their template card so
  the instructor sees "Bed 1 (template) — 4 students: Alice, Bob,
  Cara, Dan" rather than 5 unrelated cards.
- **No scoring against `activity.answer_key`** in M14 yet. The
  answer key exists (M11), but the matcher between
  student-charted events and the key's expected findings is a v7.1
  module. Once it lands, the Analysis block gains a rubric-score
  field per encounter.
