"""FR-013a — Local context layer (P1: data model + library store + CRUD).

A program-wide library of LOCAL-PRACTICE items — standing orders, formulary
entries, treatment priorities — that the clinical/character turn consults AFTER
best practices, so the sim "speaks local". Authored + reviewed data (never
trainee free-text, ADR-0014); each item is Active or Inactive (FR-008 posture:
nothing live until confirmed). The ACTIVE items form the LOCAL OVERLAY a session
can switch on (FR-013 P5 toggle) and that every character-turn path injects (P4)
on top of the best-practice baseline — like the FR-001/002 med board and FR-009
handoff blocks.

Stored as a reviewable JSON library on disk under portal/data/local_context/ —
NOT the session DB (medsim.db, which reset.sh archives), because the library is
program-wide authored data that must persist across sessions + the clean-slate
reset. PHI-free by construction.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Program-wide authored library — persists across sessions (deliberately NOT in
# ~/.medsim/v7/medsim.db, which reset.sh archives). One small JSON file. Tests
# monkeypatch these module globals to isolate; _load/_save read them at call
# time so the override takes effect.
LIBRARY_DIR = Path(__file__).resolve().parent / "data" / "local_context"
LIBRARY_PATH = LIBRARY_DIR / "library.json"

# Item taxonomy (extensible). Order here is the order they render in the overlay.
ITEM_TYPES: tuple[str, ...] = ("standing_order", "medication", "treatment_priority")

_TYPE_LABEL = {
    "standing_order":     "Standing orders",
    "medication":         "Local formulary / medications",
    "treatment_priority": "Treatment priorities",
}


@dataclass
class LocalContextItem:
    id: str
    type: str               # one of ITEM_TYPES
    title: str              # short label, e.g. "Sepsis bundle — lactate q2h"
    content: str            # the local rule / order / formulary text
    source: str = "manual"  # provenance (filename, or "manual" for hand-entry)
    active: bool = False     # nothing applies until the instructor confirms it
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load() -> list[dict[str, Any]]:
    try:
        if LIBRARY_PATH.exists():
            data = json.loads(LIBRARY_PATH.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def _save(items: list[dict[str, Any]]) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LIBRARY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2), "utf-8")
    tmp.replace(LIBRARY_PATH)   # atomic swap — never leave a half-written library


# ── CRUD ────────────────────────────────────────────────────────────────

def list_items() -> list[dict[str, Any]]:
    """Every library item (active + inactive), newest last."""
    return _load()


def active_items() -> list[dict[str, Any]]:
    return [it for it in _load() if it.get("active")]


def get_item(item_id: str) -> dict[str, Any] | None:
    return next((it for it in _load() if it.get("id") == item_id), None)


def add_item(*, type: str, title: str, content: str,
             source: str = "manual", active: bool = False) -> dict[str, Any]:
    if type not in ITEM_TYPES:
        raise ValueError(f"unknown item type {type!r}")
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        raise ValueError("title and content are required")
    item = LocalContextItem(
        id="lc_" + uuid.uuid4().hex[:12], type=type, title=title,
        content=content, source=(source or "manual").strip() or "manual",
        active=bool(active), created_at=time.time()).to_dict()
    items = _load()
    items.append(item)
    _save(items)
    return item


def update_item(item_id: str, **patch: Any) -> dict[str, Any] | None:
    """Edit / re-type / (de)activate an item. Unknown id → None."""
    items = _load()
    for it in items:
        if it.get("id") != item_id:
            continue
        if patch.get("type") is not None and patch["type"] not in ITEM_TYPES:
            raise ValueError(f"unknown item type {patch['type']!r}")
        for k in ("type", "title", "content", "source"):
            if patch.get(k) is not None:
                it[k] = str(patch[k]).strip()
        if "active" in patch and patch["active"] is not None:
            it["active"] = bool(patch["active"])
        _save(items)
        return it
    return None


def remove_item(item_id: str) -> bool:
    items = _load()
    kept = [it for it in items if it.get("id") != item_id]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True


# ── Prompt overlay (consumed by FR-013 P4 — inject in every turn path) ────

def prompt_block(enabled: bool = True) -> str:
    """Assemble the LOCAL-CONTEXT overlay block from the ACTIVE library items,
    grouped by type. Returns '' when disabled or there are no active items, so a
    turn-card injection is a clean no-op in pure-best-practice mode.

    FR-013 P5's per-session toggle passes `enabled`; P4 injects the result into
    the character turn AFTER the best-practice baseline (local refines/overrides,
    never invents)."""
    if not enabled:
        return ""
    items = active_items()
    if not items:
        return ""
    lines = [
        "LOCAL PRACTICE OVERLAY — this site's standing orders, formulary, and "
        "treatment priorities. Apply these ON TOP OF best practice; where a "
        "local item differs from best practice, FOLLOW THE LOCAL ITEM. Do not "
        "invent protocols beyond what is listed here.",
    ]
    for t in ITEM_TYPES:
        group = [it for it in items if it.get("type") == t]
        if not group:
            continue
        lines.append(f"\n{_TYPE_LABEL[t]}:")
        for it in group:
            lines.append(f"  - {it.get('title')}: {it.get('content')}")
    return "\n".join(lines)


# ── Program-wide overlay toggle (FR-013 P5) ───────────────────────────────
# ONE persisted on/off flag for the whole install. The library is program-wide
# and this single-instructor portal runs one scenario/room at a time, so a
# single switch (not a per-session flag threaded through every turn path) is the
# right grain for the MVP. Default OFF = pure best practice. The Set-up page
# flips it; every character-turn path reads it at TURN TIME via overlay_block().
# Stored beside the library (program data — reset.sh keeps it, not session
# state). Path derived from LIBRARY_DIR at call time so a test's monkeypatch of
# LIBRARY_DIR isolates the toggle too.

def _settings_path() -> Path:
    return LIBRARY_DIR / "settings.json"


def is_enabled() -> bool:
    """Whether the LOCAL-PRACTICE overlay is switched on program-wide."""
    try:
        p = _settings_path()
        if p.exists():
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, dict):
                return bool(data.get("enabled", False))
    except (OSError, ValueError):
        pass
    return False


def set_enabled(enabled: bool) -> bool:
    """Persist the program-wide overlay toggle; returns the stored value."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    p = _settings_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"enabled": bool(enabled)}, indent=2), "utf-8")
    tmp.replace(p)   # atomic swap
    return bool(enabled)


def overlay_block() -> str:
    """The local overlay a CHARACTER-TURN PATH injects (FR-013 P4): the active-
    items block when the program toggle is ON, else ''. One call, no session key
    — the toggle is program-wide. A clean no-op ('') in pure-best-practice mode
    or with no active items, so every turn path can add it unconditionally next
    to the med_orders / med_errors / handoff blocks."""
    return prompt_block(is_enabled())
