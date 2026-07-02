"""Map V8 internals to contract envelopes. The ONLY module that imports V8 internals.
Shapes follow V8's control_session / control_room / debrief / auth objects. V8 is a
'tenant of one', so tenant_id is the configured LOCAL_TENANT_ID."""
from __future__ import annotations
from typing import Any

from . import config, contract

SOURCE = "v8"

# identity.provide primary_role (contract roles.catalog) -> V8 operator seat.
# Deny-by-default: roles with no V8-operational authority (students, researcher,
# billing, V9-native planes) and UNKNOWN roles map to None — the login then falls
# back to the locally-unlocked seat, never errors (forward-compat rule: a new hub
# role must be ignored+denied, not crash a V8 site).
_HUB_ROLE_TO_SEAT = {
    "TB-SA": "admin", "ORG-ADMIN": "admin", "SITE-ADMIN": "admin", "SIM-MGR-A": "admin",
    "INSTR": "instructor", "SIM-MGR-I": "instructor",
    "INSTR-AST": "observer", "OBSERVER": "observer",
}


def seat_from_identity(ident: dict[str, Any]) -> str | None:
    """V8 seat ('admin'/'instructor'/'observer') for an identity.provide payload,
    or None when the identity grants no V8 seat (inactive, unknown role, or a
    role with no on-prem authority)."""
    if not ident or ident.get("status") != "active":
        return None
    session = ident.get("session") or {}
    if session.get("valid") is False:
        return None
    return _HUB_ROLE_TO_SEAT.get(str(ident.get("primary_role") or ""))


def _t(tenant_id: str | None) -> str:
    return tenant_id or config.LOCAL_TENANT_ID


def session_event(*, type: str, session_id: str, tenant_id: str | None = None,
                  room_id: str = "", encounter_id: str = "", station: dict[str, Any] | None = None,
                  participant_ref: str = "", resumable: bool = True) -> dict[str, Any]:
    """ControlRoom / ControlSession (Encounter) lifecycle -> session.*"""
    payload: dict[str, Any] = {"session_id": session_id, "resumable": resumable}
    for k, v in (("room_id", room_id), ("encounter_id", encounter_id),
                 ("participant_ref", participant_ref)):
        if v:
            payload[k] = v
    if station:
        payload["station"] = station        # {station_id, kind, modality, vendor}
    return contract.make_envelope(domain="session", type=type, tenant_id=_t(tenant_id),
                                  source=SOURCE, payload=payload)


def reporting_record(*, record: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
    """V8 debrief (data/debriefs/<id>.json), reduced to the PHI-free, xAPI-shaped
    unified record -> reporting.record.completed. Strip transcript before calling."""
    return contract.make_envelope(domain="reporting", type="reporting.record.completed",
                                  tenant_id=_t(tenant_id), source=SOURCE, payload=record)


def metering_turn(*, metric: str, qty: int = 1, encounter_id: str = "",
                  tenant_id: str | None = None) -> dict[str, Any]:
    """V8 budgets counters (RoomBudgetTracker) -> metering.usage. Promotes the
    in-process counters to durable, billable facts via the queue."""
    payload = {"metric": metric, "qty": qty, "scope": {"encounter_id": encounter_id}}
    return contract.make_envelope(domain="metering", type="metering.usage",
                                  tenant_id=_t(tenant_id), source=SOURCE, payload=payload)


def audit_event(*, actor: str, action: str, object_type: str = "", object_id: str = "",
                tenant_id: str | None = None) -> dict[str, Any]:
    """V8 auth / control events -> audit.event."""
    payload = {"actor": actor, "action": action,
               "object_type": object_type, "object_id": object_id}
    return contract.make_envelope(domain="audit", type="audit.event",
                                  tenant_id=_t(tenant_id), source=SOURCE, payload=payload)
