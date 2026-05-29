# M6 — Wizard step-0 mode toggle + room finalize branch

**Phase:** 3 — Dashboard
**Status:** DONE (2026-05-26)
**Blocked by:** M5
**Blocks:** M9, M10
**Estimated effort:** 2 days · **Actual:** 0.5 day (the underlying
routes from M4 and the dashboard from M5 were already in place; M6
was the wizard UI fork plus the JSON-POST branch)

---

## 1. Purpose

Add the operator-facing entry point that lets a single wizard
configure either a v6-style single-patient session **or** a v7
multi-patient ControlRoom of N encounters. The two finalize paths
share Steps 1, 2, 2b, 3, and 5 of the existing wizard; only the
"who's in the room" step differs:

- **Single patient** — Step 4 keeps the v6 persona-grid behavior. The
  form POSTs to `/portal/control/start` as before. v6 path 1:1.
- **Room of N** — Step 4 is replaced by Step 4r ("Encounters"), a
  repeatable rows editor where each row has a label + persona
  dropdown + EHR dropdown. The JS intercepts submit and JSON-POSTs
  to `/api/room/start` (M4), then lands the operator on
  `/portal/room` (M5).

## 2. Structure

**Files touched:**
- `portal/templates/control.html` — adds the Mode toggle above
  `wizard-steps`, the hidden Step 4r pane, and exposes
  `personasForRoom` + `ehrIds` to JS via `window.MEDSIM2`.
- `portal/static/control.js` — refactors the step sequence to
  switch between `4` (single) and `4r` (room) based on the toggle.
  Adds `applyMode`, `renderRoomEncounterRows`, validation for Step
  4r, and `submitRoom` (the JSON-POST branch).
- `portal/static/control.css` — `.mode-toggle`, `.mode-card`,
  `.encounter-editor`, `.encounter-row` styling (responsive down to
  the 700 px breakpoint).

**No server.py changes** — the room-mode submit goes to the M4
`/api/room/start` route, which already exists and is tested.

## 3. Uses

- The operator opens `/portal/control` from the nav.
- They pick a mode (defaults to Single Patient — the v6 default).
- They fill the shared steps (Scenario, EHR, Curriculum).
- **Single mode:** Step 4 (Characters) → Step 5 (Network) → Submit.
  Lands on `/portal/control/ops` (v6 single-encounter ops view).
- **Room mode:** Step 4r (Encounters) — set N + per-row label +
  persona + EHR → Step 5 → Submit. Lands on `/portal/room` (M5's
  charge-nurse dashboard).

## 4. Functions (exported API surface)

### Template (control.html)

| Element | Role |
|---------|------|
| `.mode-toggle .mode-card[data-mode=single]` | Single Patient radio card. |
| `.mode-toggle .mode-card[data-mode=room]`   | Room of N radio card.       |
| `.step[data-step="4"][data-step-single]`    | Single-mode Step 4 strip entry. |
| `.step[data-step="4r"][data-step-room]`     | Room-mode Step 4r strip entry (hidden in single mode). |
| `.wiz-pane[data-pane="4r"][data-pane-room]` | Room-mode encounter editor pane. |
| `#room-n` input                              | How many encounters (2–10). |
| `#room-chart-mode` select                    | shared / private_clone default. |
| `#room-encounter-rows` div                   | Container; JS appends `.encounter-row` children. |

### JS (control.js — IIFE, no public exports)

| Internal symbol | Purpose |
|-----------------|---------|
| `buildSequence(mode)` | Returns the active step-id sequence, swapping `4` ↔ `4r` based on mode. |
| `applyMode(newMode)` | Mode flip: updates `.mode-card.active`, hides off-mode strip entries + panes, rebuilds the sequence, jumps to step 1. |
| `renderRoomEncounterRows()` | Renders N rows in `#room-encounter-rows`, preserving any operator-typed values between re-renders. |
| `submitSingle(result)` | v6 form POST to `/portal/control/start`. Strips `wizard_mode`. |
| `submitRoom(result)` | Validates rows; builds a `{label, encounters: [...]}` JSON body; POSTs to `/api/room/start`; redirects to `/portal/room`. |
| `validateStep(id)` extension | Adds Step 4r validation: ≥2 rows, every row has a persona. |

### `window.MEDSIM2` additions

```js
personasForRoom: [{id, name, role}, ...]   // 24 personas, compact form
ehrIds:          [{id, name}, ...]         // helix / cyrus / meridian
```

## 5. Limitations

- **Per-encounter persona is one persona.** The v6 wizard's
  "multi-persona conversation" pattern (e.g. patient + family
  member in one encounter) is single-mode-only. To replicate it in
  room mode, configure two encounters or add the secondary persona
  later via M4's per-encounter routes.
- **No per-encounter Curriculum override.** Every encounter in a
  room inherits the same `program_id`, `week`, `modules`, and
  `scenario_text` from the shared Steps 2/3. Per-encounter
  curriculum picks are an M11/M12 (Activity catalog) feature once
  the catalog exists.
- **Range 2–10 encounters.** Below 2 doesn't make sense in room
  mode (use Single Patient instead); above 10 hits M19's eventual
  capacity cap (24 stations / 10 encounters per the Development
  Plan §"Capacity caps").
- **Mode toggle resets navigation to Step 1.** This is deliberate —
  toggling mid-flow can leave the operator on a step that no longer
  exists in the new mode. The trade-off: re-walking Steps 1–3 after
  a mode switch.
- **Step 5 is shared between modes.** The "Start session" button
  triggers the right submit branch via the JS `mode` variable;
  there's no visible UI hint of which target URL fires.

## 6. Test status

### Automated (tests/v7/test_wizard_room_modes.py)

| Test | Asserts | Status | Last run |
|------|---------|--------|----------|
| `test_wizard_single_patient_creates_implicit_room_of_one` | v6 form POST creates a room of 1; `get_active()` returns it. | PASS | 2026-05-26 |
| `test_wizard_room_of_4_creates_4_encounters` | Room-mode JSON POST creates 4 encounters with distinct join codes; `chart_mode` per-row carried through. | PASS | 2026-05-26 |
| `test_wizard_room_of_4_dashboard_state_reflects_each_encounter` | `/api/room/state` returns one row per encounter after a room finalize. | PASS | 2026-05-26 |
| `test_wizard_room_finalize_replaces_prior_single_patient_room` | Operator demos single → switches to room: prior session ends, new room owns only the new encounters. | PASS | 2026-05-26 |

4/4 — **PASS** under the v6 venv. Full v7 suite: 27/27 passing.
Full v6 regression on v7: 138 passed, 6 pre-existing env-flaky (same
list as v6 baseline), **0 v7 regressions**.

### Manual (browser preview — 2026-05-26)

| Flow | Result |
|------|--------|
| Open `/portal/control`, initial state | PASS — Single Patient highlighted, `4 · Characters` strip entry visible, `4 · Encounters` hidden. |
| Toggle Room of N | PASS — mode-card visual swap; step strip flips to `4 · Encounters`; Step 4r pane revealed; 4 encounter rows auto-render. |
| Change `#room-n` to 3 then 5 | PASS — rows re-render preserving the operator's typed labels for the rows still in range. |
| Fill 4 rows with distinct personas + labels, advance to Step 5, click Start | PASS — POST to `/api/room/start` succeeds; browser lands on `/portal/room` with the same 4-encounter grid as the M5 manual flow. |

## 7. Change list

| Date | Author | Change | Files |
|------|--------|--------|-------|
| 2026-05-26 | claude-code | Mode toggle + Step 4r pane in `control.html`; mode/sequence/row-renderer/`submitRoom` in `control.js`; `.mode-toggle`/`.encounter-row` CSS. 4 acceptance tests. Browser-verified end-to-end finalize through `/portal/room`. | `portal/templates/control.html`, `portal/static/control.{js,css}`, `tests/v7/test_wizard_room_modes.py` |

## 8. Open questions / known issues

- Mode-toggle UX on shrunken screens: at < 540 px wide the two
  mode cards stack; OK for now but may need tablet portrait
  re-verification in M21's LAN test.
- The "Default chart mode" select on Step 4r only sets the
  per-encounter default. If a future requirement is "per-row chart
  mode override," the row template already has the data slot but
  there's no row-level UI control yet.
- The room mode's finalize discards the in-form persona checkboxes
  from Step 4 (which is hidden anyway). If the operator filled Step
  4 in single mode, then toggled to room mode, the persona
  checkboxes silently no-op — which is the right behavior (the
  toggle restarts navigation to Step 1) but worth a UX confirm in
  M21 LAN testing.
- `applyMode` triggers a navigation reset to step 1. We could
  preserve `current` if it's still in the new sequence, but the
  reset is intentional defensive behavior — toggling mid-flow is a
  rare operator action.
