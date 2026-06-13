# FR-011 G1 (ADR-0039) — portal resumability aggregator.
#
# Extends Memory_management ADR-0018 (tablet pause/resume) to the PORTAL: each
# stateful module exposes a PHI-FREE structured snapshot()/restore(); this module
# aggregates them into ONE versioned blob and persists it to the SAME
# restart-durable SQLite the EHR chart already survives in (~/.medsim/v7). A
# graceful restart (SIGTERM) persists on shutdown; boot restores. The educator's
# session config + med board + staged errors + handoff survive a restart instead
# of being wiped — killing the "fresh Setup every restart" friction.
#
# PHI: trainee free-text is NEVER in the blob (ADR-0014). The per-module
# snapshots already exclude the transcript, survey answers, and evaluation
# quotes; this module never adds any.

from __future__ import annotations

import json
import time
from typing import Any, Callable

VERSION = 1


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001 — resumability is best-effort, never fatal
        return None


def snapshot() -> dict[str, Any] | None:
    """Aggregate the live portal state into one versioned, PHI-free blob. None
    when there is nothing worth saving (no active control session)."""
    from . import control_session, handoff, med_errors, med_orders
    cs = _safe(control_session.snapshot)
    if not cs:
        return None
    return {
        "version": VERSION,
        "saved_at": time.time(),
        "control_session": cs,
        "med_orders": _safe(med_orders.snapshot) or {},
        "med_errors": _safe(med_errors.snapshot) or {},
        "handoff": _safe(handoff.snapshot) or {},
    }


def persist() -> bool:
    """Snapshot the live state and write it to the durable store. False when
    there is nothing to save. Never raises (called from the shutdown hook)."""
    blob = _safe(snapshot)
    if not blob:
        return False
    try:
        from . import ehr_db
        ehr_db.save_session_state(json.dumps(blob, default=str))
        return True
    except Exception:  # noqa: BLE001
        return False


def load_latest() -> dict[str, Any] | None:
    try:
        from . import ehr_db
        raw = ehr_db.load_session_state()
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def resume() -> dict[str, Any] | None:
    """Restore every module from the latest snapshot. Returns a small summary
    (or None if there was nothing / it was incompatible). Best-effort + version-
    tolerant; never raises — a bad blob yields a clean empty start, not a crash."""
    blob = load_latest()
    if not blob or blob.get("version") != VERSION:
        return None
    from . import control_session, handoff, med_errors, med_orders
    # The control session FIRST (re-establishes the session ids the keyed
    # module state references); bail if it can't be restored.
    if not _safe(lambda: control_session.restore(blob.get("control_session"))):
        return None
    _safe(lambda: med_orders.restore(blob.get("med_orders") or {}))
    _safe(lambda: med_errors.restore(blob.get("med_errors") or {}))
    _safe(lambda: handoff.restore(blob.get("handoff") or {}))
    encs = (blob.get("control_session") or {}).get("encounters") or []
    return {
        "saved_at": blob.get("saved_at"),
        "n_encounters": len(encs),
        "names": [e.get("scenario_name") for e in encs if isinstance(e, dict)],
    }


def clear() -> None:
    try:
        from . import ehr_db
        ehr_db.clear_session_state()
    except Exception:  # noqa: BLE001
        pass
