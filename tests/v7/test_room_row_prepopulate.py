"""M40 — Pre-populate Room of N Characters + Curriculum drawers from Activity.

The single-patient wizard's Step 2 template picker calls
`applySample(s)` which checks every persona checkbox in `s.personas`
and every module checkbox in `s.modules`. In Room of N mode the
per-row Activity picker stashed the seed data but left the drawer
checkboxes empty — the operator had to manually re-check them
every time.

M40 wires the Activity-change handler to mirror `applySample`:
check `[data-row-persona][value=<seed_persona_id>]` and
`[data-row-module][value=<each seed_module>]`. Also auto-checks
the primary persona when the row's persona dropdown changes.

Drawer state is also preserved across row re-renders (when the
operator bumps the room-N input).

These are JS-source guards — a full browser-driven test belongs in
the M20 Playwright suite. We assert here that the wiring is in
place so a refactor doesn't silently regress.
"""
from __future__ import annotations

from pathlib import Path


CONTROL_JS = (
    Path(__file__).resolve().parents[2]
    / "portal" / "static" / "control.js"
)


def _src() -> str:
    return CONTROL_JS.read_text(encoding="utf-8")


def test_activity_handler_checks_seed_persona_checkbox() -> None:
    """The Activity-change handler must check the data-row-persona
    checkbox matching the activity's seed_persona_id — same as
    applySample does for the single-patient persona grid."""
    src = _src()
    # Locate the activity change handler.
    idx = src.find('ev.target.dataset?.field !== "activity"')
    assert idx >= 0, "activity change handler not found"
    handler_block = src[idx:idx + 3000]
    # Must reference seed_persona_id and check a data-row-persona
    # checkbox by value.
    assert "a.seed_persona_id" in handler_block
    assert "data-row-persona" in handler_block
    assert "personaCb.checked = true" in handler_block or \
           "personaCb.checked=true" in handler_block


def test_activity_handler_checks_each_seed_module_checkbox() -> None:
    """For each seed_module, the handler must check the matching
    data-row-module checkbox in the row's Curriculum drawer."""
    src = _src()
    idx = src.find('ev.target.dataset?.field !== "activity"')
    handler_block = src[idx:idx + 3000]
    # The handler must iterate data-row-module checkboxes.
    assert "data-row-module" in handler_block
    # And reference a.seed_modules.
    assert "a.seed_modules" in handler_block or \
           "seed_modules" in handler_block
    # And use a Set + querySelectorAll iteration pattern.
    assert "new Set(seedModules)" in handler_block
    assert "row.querySelectorAll('[data-row-module]')" in handler_block


def test_activity_handler_refreshes_badge_counts() -> None:
    """After the auto-check, the badges on the tab strip must
    update so the operator sees the count climb (Characters · 3,
    Curriculum · 5) without having to expand the drawer."""
    src = _src()
    idx = src.find('ev.target.dataset?.field !== "activity"')
    # Window large enough to span the full handler body (the seed-
    # module loop pushes the badge refresh past the 3000-char mark).
    handler_block = src[idx:idx + 5000]
    assert "updateRowTabBadges(row)" in handler_block


def test_persona_dropdown_change_auto_checks_characters_drawer() -> None:
    """When the operator picks a different primary persona on a row,
    the Characters drawer should auto-check that persona — same
    'primary is always part of the cast' invariant the submit logic
    enforces, surfaced earlier in the UI."""
    src = _src()
    # Look for the persona-dropdown change handler.
    assert 'ev.target.dataset?.field !== "persona"' in src, (
        "Persona-dropdown change handler not found — M40 added it.")
    # The handler must check a data-row-persona checkbox and refresh
    # badges.
    idx = src.find('ev.target.dataset?.field !== "persona"')
    handler_block = src[idx:idx + 600]
    assert "data-row-persona" in handler_block
    assert "updateRowTabBadges(row)" in handler_block


def test_updateRowTabBadges_helper_exists() -> None:
    """Shared helper that reads the row's checkbox state and writes
    the two badge counts. Used by both the Activity handler and the
    persona-dropdown change handler."""
    src = _src()
    assert "function updateRowTabBadges" in src
    body_idx = src.find("function updateRowTabBadges")
    body = src[body_idx:body_idx + 600]
    assert "data-row-persona" in body
    assert "data-row-module" in body
    assert "row-tab-count" in body


def test_prev_capture_includes_drawer_state() -> None:
    """When N changes and renderRoomEncounterRows re-runs, the
    `prev` array must include each row's drawer state
    (personaList, modulesList, programId, week) so the re-render
    doesn't wipe the operator's selections."""
    src = _src()
    # Locate the prev array construction.
    idx = src.find("const prev = Array.from(host.querySelectorAll")
    assert idx >= 0
    block = src[idx:idx + 1500]
    assert "personaList" in block
    assert "modulesList" in block
    assert "programId" in block
    # The week field is captured as a string from the input.
    assert "week:" in block


def test_row_render_uses_existing_persona_and_module_lists() -> None:
    """Sanity-check the existing render code still consumes the
    captured drawer state — without this, M40's prev-capture changes
    would be inert."""
    src = _src()
    # Persona checkboxes use existing.personaList.
    assert "(existing.personaList || []).includes(p.id)" in src
    # Module checkboxes use existing.modulesList.
    assert "(existing.modulesList || []).includes(m.id)" in src


def test_cssEscape_polyfill_exists() -> None:
    """Persona IDs go into attribute selectors — the polyfill keeps
    the lookup safe even if a future catalog adds a non-identifier id."""
    src = _src()
    assert "function cssEscape" in src
    assert "CSS.escape" in src
