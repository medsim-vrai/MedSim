# M32 — Room mode skips wizard's single-patient steps

**Phase:** Phase 7 follow-on (post-M31, operator-feedback fix)
**Status:** **DONE**
**Blocked by:** M6 (mode toggle), M12 (per-row activity picker), M31 (per-row Characters + Curriculum drawers)
**Blocks:** none
**Estimated effort:** 0.5 day

---

## 1. Purpose

Operator feedback after M31:

> "For the multi patient the system still follows the path for the
> single patient then has the encounter page."

In Room of N mode, the wizard previously walked the instructor
through Steps 1 → 2 (Scenario) → 2b (Records system) → 3 (Curriculum
context) → 4r (Encounters) → 5 (Network). Steps 2 / 2b / 3 are
single-patient wizard-wide fields — they had no authoring meaning in
room mode because Step 4r's per-row drawers (M31) own all of that
authoring per bed. The instructor was effectively filling out a
ghost single-patient session before getting to the real work.

M32 removes those steps from the room-mode flow. The instructor's
path is now:

```
Room of N mode:  Step 1 (system check) → Step 4r (per-bed authoring) → Step 5 (network launch)
Single mode:     Step 1 → Step 2 → Step 2b → Step 3 → Step 4 → Step 5   (unchanged)
```

Each Step 4r encounter row continues to expose three drawers
(Scenario, Characters, Curriculum) introduced in M31 — those drawers
are now the *only* place per-bed authoring happens. The visible step
strip is renumbered to its sequence position, so room mode reads
*"1 · System check  ·  2 · Encounters  ·  3 · Network"* instead of
the gappy *"1 · System check  ·  2 · Encounters  ·  5 · Network"*.

A new "Room label" input lives at the top of Step 4r so the cohort
gets a name without resurrecting Step 2.

## 2. Structure

**Files touched:**
- `portal/templates/control.html` — step-strip indicators 2 / 2b / 3
  marked `data-step-single`; panes 2 / 2b / 3 marked `data-pane-single`;
  `data-required-single` added to the `scenario_name` input; Step 4r
  intro rewritten + Room label input added; Step 4r step-strip text
  changed from "4 · Encounters" to "2 · Encounters" (default — JS
  renumbers live based on sequence position).
- `portal/static/control.js` — `applyMode()` hides `data-pane-single`
  panes in room mode; toggles `required` on `data-required-single`
  fields based on mode; new `refreshStepNumbers()` rewrites visible
  step prefixes from sequence position; `submitRoom()` reads the
  room label from `#room-label-input` (with fallbacks).

**No backend change.** `/api/room/start` already accepts every field
M31 added; M32 is a pure UX rewire.

**No schema migration.** No new dataclass fields.

## 3. Uses

### 3.1 Instructor flow (room mode)

1. `/portal/control` loads → wizard mode picker defaults to **Single**.
2. Instructor clicks **Room of N** card.
3. `applyMode("room")` runs:
   - Step strip steps 2 / 2b / 3 / 4 become `hidden`.
   - Step strip step 4r becomes visible.
   - Panes 2 / 2b / 3 become `hidden`.
   - `scenario_name`'s `required` attribute is removed.
   - `refreshStepNumbers()` renumbers visible step labels to
     "1 · System check", "2 · Encounters", "3 · Network".
   - `renderRoomEncounterRows()` paints N rows into Step 4r.
   - `showStep("1")` lands the instructor on the system check.
4. Step 1 → Continue → Step 4r (skipping 2 / 2b / 3 entirely).
5. Step 4r: instructor fills in Room label + N + chart mode, then
   opens the three drawers per row (M31). The Scenario drawer holds
   that bed's scenario textarea (M12-era per-row Activity picker
   pre-fills it); the Characters drawer is the persona multi-select;
   the Curriculum drawer is the per-bed program / week / module set.
6. Continue → Step 5 → "Start session →" → `submitRoom()` POSTs to
   `/api/room/start` with one encounter object per row, each
   carrying its own personas / modules / program / week / EHR /
   scenario_text / chart_mode / label.
7. Browser redirects to `/portal/room` (Multi-Patient Control
   dashboard).

### 3.2 Step renumbering

The step strip in HTML carries each step's stable `data-step` id
(`"1"`, `"2"`, `"2b"`, `"3"`, `"4"`, `"4r"`, `"5"`) plus the
display text (e.g. `"4 · Encounters"`). On `applyMode()`,
`refreshStepNumbers()` finds each step that's in the current
`sequence` array and rewrites its text to
`${sequenceIndex + 1} · ${labelBody}`. The label body
(everything after the original "N · " prefix) is cached on
`dataset.labelBody` on first visit so successive mode toggles
don't compound. Steps not in the active sequence are left alone
(they're `hidden` anyway).

## 4. Functions (exported API surface)

No new public functions — M32 is a UX/template change.

| Symbol | Where | Purpose |
|--------|-------|---------|
| `applyMode(newMode)` | `portal/static/control.js` | Extended: hides single-mode panes + toggles `required` + calls `refreshStepNumbers()`. |
| `refreshStepNumbers()` (new) | `portal/static/control.js` | Rewrites visible step labels based on sequence position. Cached `dataset.labelBody` makes toggle idempotent. |
| `submitRoom(result)` | `portal/static/control.js` | Now reads room label from `#room-label-input` first, then the (hidden) `scenario_name` second, then a literal fallback. |

## 5. Limitations

- **The Scenario drawer per row is still collapsed by default.**
  An instructor who only wants to assign primary personas + activities
  per row can still finalize without opening drawers — Activity picks
  pre-fill the scenario textarea inside the drawer, so the row remains
  authored even when the drawer is closed.
- **Mode toggle mid-flow resets to step 1.** If the instructor has
  partially completed Step 4r in room mode and then flips to single,
  they restart at Step 1. The per-row state in the (now-hidden) Step 4r
  is preserved in DOM but inaccessible until they toggle back to room
  mode. Matches the M6 design.
- **Step 4r is still a single scrolling pane.** With 10 beds and all
  three drawers expanded per row, that's a long page. The drawers are
  collapsed by default to mitigate; a future M33 could paginate or
  use a left-rail jump list per bed.
- **No per-bed "Records system" Step-2b-equivalent inside the
  Characters drawer.** Each row already has an `ehr_id` `<select>` in
  its primary controls row — that's where per-bed EHR picking lives.
  No dedicated drawer for it.
- **Step prefix renumbering happens once per mode change.** If JS
  later mutates `sequence` without re-calling `refreshStepNumbers()`,
  the visible numbers will drift. All current call sites flip mode
  via `applyMode()`, which calls the refresh, so this is fine today.

## 6. Test status

| Test file | Asserts | Status | Last run |
|-----------|---------|--------|----------|
| `tests/v7/test_wizard_room_mode_skips_single_steps.py::test_step_strip_marks_single_only_steps` | step strip indicators 2 / 2b / 3 / 4 carry `data-step-single` | PASS | 2026-05-27 |
| `tests/v7/test_wizard_room_mode_skips_single_steps.py::test_single_only_panes_carry_data_pane_single` | panes 2 / 2b / 3 carry `data-pane-single` | PASS | 2026-05-27 |
| `tests/v7/test_wizard_room_mode_skips_single_steps.py::test_step_4r_has_dedicated_room_label_input` | `#room-label-input` exists inside the Step 4r pane | PASS | 2026-05-27 |
| `tests/v7/test_wizard_room_mode_skips_single_steps.py::test_scenario_name_required_is_conditional` | `scenario_name` carries `required` AND `data-required-single` | PASS | 2026-05-27 |
| (regression update) `tests/v7/test_wizard_per_row_scenario.py::test_wizard_template_includes_per_row_scenario_textarea` | Step 4r intro copy reflects "each bed is its own scenario" — assertion updated to match new phrasing | PASS | 2026-05-27 |
| **Full v7 suite** | **204 passed, 1 skipped** (M20 Playwright skip — unchanged) | PASS | 2026-05-27 |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-27 | claude-code | Initial M32 implementation: mark single-only steps + panes, add Room label input + `data-required-single`, renumber step prefixes, 4 new tests, 1 phrase-only test fix | `portal/templates/control.html`, `portal/static/control.js`, `tests/v7/test_wizard_room_mode_skips_single_steps.py` (new), `tests/v7/test_wizard_per_row_scenario.py` (assertion text only) |

## 8. Open questions / known issues

- **The Activities picker dropdown on each Step 4r row carries a
  "Custom (no template)" option.** Without Step 2's wizard-wide
  scenario textarea, a row with "Custom" + a closed Scenario drawer
  effectively has no scenario text. The submit handler still resolves
  to `scenarioText` (the hidden Step 2 field, empty) as fallback. We
  may want to make the Scenario drawer auto-expand when the row's
  activity is "Custom" and the textarea is empty. Tracked as a
  potential M33 follow-up.
- **Step 5 ("Network") still mentions a single "join code" QR.**
  In room mode each bed has its own join code (M31), so the Step 5
  copy should be revisited to reflect that — but the per-bed QRs
  live on the Per-Patient Console (M31), not on Step 5. Acceptable
  for now; copy refresh deferred.
- **The room label is optional.** If the instructor leaves
  `#room-label-input` empty and `scenario_name` empty, the cohort
  is labeled `"Room"`. We could `required`-flag the room label but
  the existing fallback feels operator-friendly.

---

*Render this guide to PDF with `python docs/module_guides/render_pdfs.py`.*
