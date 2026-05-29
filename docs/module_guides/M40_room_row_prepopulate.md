# M40 — Pre-populate Room of N Characters + Curriculum drawers from Activity

**Phase:** Phase 7 follow-on (post-M39, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M12 (Activity catalog + per-row picker), M31 (per-row Characters/Curriculum drawers)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M39:

> "For Room of N for the encounters the characters and curriculum
> should pre-populate like they do for the single character."

In the single-patient wizard, picking a sample at Step 2 calls
`applySample(s)` which:

- Sets `scenario_name`, `scenario_notes`, `scenario_text`.
- Sets the program + week selects + populates the week-derived
  module list.
- Checks every persona checkbox in `s.personas`.
- Checks every module checkbox in `s.modules`.

In Room of N mode (M31), picking an Activity on a row already
pre-filled the scenario textarea + label + primary persona dropdown
and stashed `seed_modules` into a dataset for submit. But the
**drawer checkboxes stayed empty** — the operator had to manually
open the Characters drawer and check the persona, open the
Curriculum drawer and check every module. Even though the seed
data was there, the UI didn't surface it.

M40 mirrors `applySample`'s drawer-population step for each row.
Plus two related fixes:

1. When the row's primary persona dropdown changes, auto-check the
   matching Characters-drawer checkbox (the "primary is always part
   of the cast" invariant the submit logic enforced at the end —
   now surfaced earlier in the UI).
2. When the operator bumps the room-N input, `renderRoomEncounterRows`
   re-renders every row from the captured `prev` array. M40 extends
   `prev` to also capture each row's drawer state (personaList,
   modulesList, programId, week) so re-renders don't wipe the
   operator's selections.

## 2. Structure

**Files touched:**
- `portal/static/control.js`:
  - Extended the Activity-change handler (`document.addEventListener
    ("change", ...)` for `[data-field="activity"]`) — after stashing
    seed data and pre-filling the textarea, programmatically check
    `[data-row-persona][value=<seed_persona_id>]` and every
    `[data-row-module][value=<each seed_module>]`. Refresh tab-strip
    badges via the new helper.
  - New `cssEscape(s)` polyfill — defensively quotes persona/module
    ids for attribute selectors. Falls through to `CSS.escape` when
    available.
  - New `updateRowTabBadges(row)` helper — reads checkbox state,
    writes both badge counts. Single source of truth for row badge
    arithmetic.
  - New persona-dropdown change handler — when
    `[data-field="persona"]` changes on a row, auto-check the
    matching Characters-drawer checkbox and refresh badges.
  - `renderRoomEncounterRows` `prev` capture — now reads
    `personaList`, `modulesList`, `programId`, `week` from each row
    before re-rendering. The existing render code already consumed
    `existing.personaList` / `existing.modulesList` / `existing.
    programId` / `existing.week`; this fills those reads with the
    operator's actual prior state.

**No backend change. No HTML/CSS change. No new dataclass field.**

## 3. Uses

### 3.1 Operator flow

1. Operator goes through wizard → Room of N → Step 4r (Encounters).
2. Each row defaults: empty drawers, primary persona dropdown set
   to the first persona in the catalog.
3. Operator picks an Activity on row 1 — say *"ED Sepsis"* with
   `seed_persona_id = "P-014"` and `seed_modules = ["M32", "M08",
   "M02"]`.
4. **Old behavior**: scenario textarea + label + primary persona
   dropdown updated; drawer checkboxes stayed empty; submitting
   sent the row with only the primary persona + (via dataset
   fallback) the seed modules. Operator had no way to know seed
   modules would land — had to trust the dataset.
5. **New behavior (M40)**: same updates PLUS:
   - Characters drawer's `P-014` checkbox is now checked.
   - Curriculum drawer's `M32`, `M08`, `M02` checkboxes are all
     checked.
   - Badge strip on the row updates: `Characters · 1`,
     `Curriculum · 3`.
   - Operator can immediately open either drawer and see exactly
     what will be sent — and add or uncheck as needed.
6. If the operator picks a *different* primary persona via the
   row's persona dropdown (after the Activity pick), the new
   persona's checkbox in the Characters drawer auto-checks too
   (without unchecking the previous one — multi-cast intent).
7. If the operator bumps the room-N input from 4 to 6, the four
   existing rows re-render preserving all their drawer state. The
   two new rows render empty.

### 3.2 Why mirror `applySample` semantics exactly

Operators move between single-patient and Room of N modes within
the same session. Carrying the same mental model — "picking a
template fills the persona + module checkboxes" — across both
modes removes a class of confused-operator bug reports. The
behavior should be:

| Single-patient pick a sample | Room of N pick an Activity |
|-------------------------------|----------------------------|
| Fill `scenario_name` + notes  | Fill row's `label` (M12)     |
| Check personas                | **Check row's Characters drawer (M40)** |
| Check modules                 | **Check row's Curriculum drawer (M40)** |
| Set program + week            | (Activity has no program/week — left blank) |

The "set program + week" row is unfilled in Room of N because the
`Activity` dataclass (M11) doesn't currently carry `program_id` /
`week`. Out of scope for M40 — the operator can still set them per
row if they want, and the Step 3-equivalent is per-row drawer in
Room of N (since M32 hid the wizard-wide Step 3).

## 4. Functions (exported API surface)

| Symbol | Where | Purpose |
|--------|-------|---------|
| `updateRowTabBadges(row)` (new) | `portal/static/control.js` | Reads `[data-row-persona]:checked` and `[data-row-module]:checked` counts and writes both badge spans. Single source of truth. |
| `cssEscape(s)` (new) | `portal/static/control.js` | Defensive polyfill for `CSS.escape` — used to safely embed persona/module ids in attribute selectors. |
| (extended) Activity-change handler | same | After stashing seed data, checks the matching persona + module checkboxes and refreshes badges. |
| (new) Persona-dropdown change handler | same | When the row's primary persona dropdown changes, auto-checks the matching Characters-drawer checkbox. |
| (extended) `renderRoomEncounterRows` | same | `prev` capture now includes `personaList`, `modulesList`, `programId`, `week`. |

## 5. Limitations

- **Activity seed data has no program/week**. The `Activity`
  dataclass (M11) carries `seed_persona_id` (single primary) +
  `seed_modules` (list) + `scenario_text`. To also pre-fill the
  Curriculum drawer's program + week, a future M41 would need to
  extend the catalog. Out of scope today — operators can set per-
  row program + week directly in the drawer.
- **`seed_persona_id` is one persona only**. Real scenarios often
  involve a cast (patient + family + MD + RN). The Activity model
  reflects an MVP. A future M41 could carry `seed_personas: [pid,
  pid, …]`; M40 would happily check all of them.
- **Re-picking an Activity does NOT uncheck the prior Activity's
  modules**. By design — additive seed sets feel less surprising
  than wiping the drawer. Operators who want a clean slate can
  uncheck manually or pick `"— (no activity) —"` first.
- **The persona-dropdown change handler is additive too**. Picking
  a new primary doesn't uncheck the prior primary's Characters-
  drawer entry. Matches the "cast" mental model — same rationale
  as the Activity additivity above.
- **No keyboard shortcut to open/collapse all drawers**. Operators
  click row-by-row. Acceptable; the 10-encounter cap (M19) keeps
  it manageable.
- **Drawer state captured in `prev` is keyed by row position, not
  row id**. If the operator drags a row to reorder (no UI for that
  today), the captured state stays at the old position. N/A
  today; document if reordering ships.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_room_row_prepopulate.py::test_activity_handler_checks_seed_persona_checkbox` | Activity handler checks `[data-row-persona]` matching `a.seed_persona_id` | PASS | 2026-05-27 |
| `…::test_activity_handler_checks_each_seed_module_checkbox` | Handler iterates `[data-row-module]` and checks each in `Set(a.seed_modules)` | PASS | 2026-05-27 |
| `…::test_activity_handler_refreshes_badge_counts` | Handler calls `updateRowTabBadges(row)` after the auto-check | PASS | 2026-05-27 |
| `…::test_persona_dropdown_change_auto_checks_characters_drawer` | Primary-persona dropdown change handler auto-checks the matching Characters-drawer checkbox + refreshes badges | PASS | 2026-05-27 |
| `…::test_updateRowTabBadges_helper_exists` | Shared helper exists and references both data-row-* selectors + `.row-tab-count` | PASS | 2026-05-27 |
| `…::test_prev_capture_includes_drawer_state` | `prev` array captures `personaList`, `modulesList`, `programId`, `week` | PASS | 2026-05-27 |
| `…::test_row_render_uses_existing_persona_and_module_lists` | Row template still consumes `existing.personaList` / `existing.modulesList` (M31's wiring is intact) | PASS | 2026-05-27 |
| `…::test_cssEscape_polyfill_exists` | Defensive `CSS.escape` polyfill is present | PASS | 2026-05-27 |
| **Full v7 suite** | **263 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M40 implementation: Activity-handler auto-check for persona + modules; persona-dropdown change handler; updateRowTabBadges + cssEscape helpers; prev capture extended for drawer state; 8 source-guard tests | `portal/static/control.js`, `tests/v7/test_room_row_prepopulate.py` (new) |

## 8. Open questions / known issues

- **Should the Activity catalog carry program + week?** Single
  scenarios already pre-fill those at Step 2. Extending the
  `Activity` dataclass with `program_id` + `week` would close the
  parity gap. Tracked for M41.
- **Should picking a *new* Activity uncheck the prior Activity's
  modules?** M40 chose additive (don't surprise operators with
  unexplained un-checks). If LAN test feedback says the additive
  behavior feels wrong, flip to a "clear and re-fill" pattern.
- **The cast model**. Today the catalog has `seed_persona_id`
  (single). Real wedge characters (e.g. "Anxious Spouse",
  "Charge RN") exist in the persona library but aren't surfaced
  via the catalog. A `seed_personas: list[str]` field on
  `Activity` would let scenarios prescribe a full cast.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
