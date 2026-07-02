"""
Shared Integration Contract helper (v0.2.0).

Vendored identically into each product's hub_adapter so the two products and the
admin layer build the SAME envelope. Zero third-party deps (stdlib only); if
`jsonschema` happens to be installed it is used for full validation, otherwise a
light structural check runs. Keep this file byte-identical across products, or
promote it to a shared package and pin the version.

v0.2.0 (backward compatible with 0.1.0): adds the admin -> product PROVIDE direction
(source "admin"; identity/roster/entitlement types) so the admin platform can push
identity, roster and entitlements to the engines. 0.1.0 events still validate.
"""
from __future__ import annotations
import datetime
import hashlib
import hmac
import json
import uuid
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "0.2.0"
ACCEPTED_CONTRACTS = {"0.1.0", "0.2.0"}  # backward compatible

DOMAINS = {"identity", "roster", "entitlement", "session", "reporting", "metering", "audit"}
SOURCES = {"v8", "v9", "admin"}  # admin is the source for the provide direction
TYPES = {
    # product -> admin (consume)
    "session.started", "session.paused", "session.resumed", "session.ended",
    "encounter.opened", "encounter.closed", "station.joined", "station.left",
    "reporting.record.completed",
    "metering.usage",
    "audit.event",
    # admin -> product (provide) — new in v0.2.0
    "identity.upserted", "identity.deactivated",
    "roster.synced",
    "entitlement.push",
}

# The provide-direction types and the domain each belongs to (source must be "admin").
_PROVIDE_TYPES = {
    "identity.upserted": "identity",
    "identity.deactivated": "identity",
    "roster.synced": "roster",
    "entitlement.push": "entitlement",
}

# PHI rule (inherited from both products' ADR-0014): structured state only — never
# trainee free-text. Any payload carrying these keys is rejected before it leaves.
_BANNED_PHI_KEYS = {
    "transcript", "free_text", "freetext", "survey_text", "note_text",
    "evaluation_quote", "chat", "utterance", "raw_audio",
}


def new_event_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def make_envelope(*, domain: str, type: str, tenant_id: str, source: str,
                  payload: dict[str, Any], occurred_at: str | None = None,
                  event_id: str | None = None) -> dict[str, Any]:
    """Build a contract envelope. Raises ValueError if it would violate the contract."""
    evt = {
        "contract": CONTRACT_VERSION,
        "event_id": event_id or new_event_id(),
        "occurred_at": occurred_at or _now(),
        "tenant_id": tenant_id,
        "source": source,
        "domain": domain,
        "type": type,
        "schema_version": CONTRACT_VERSION,
        "payload": payload,
    }
    errors = validate_envelope(evt)
    if errors:
        raise ValueError("contract violation: " + "; ".join(errors))
    return evt


def assert_phi_free(payload: dict[str, Any]) -> None:
    """Fail closed if the payload carries any banned free-text key (recursively)."""
    def walk(o: Any, path: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() in _BANNED_PHI_KEYS:
                    raise ValueError(f"PHI-bearing key '{path}{k}' is not allowed on the wire")
                walk(v, f"{path}{k}.")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}{i}.")
    walk(payload)


def validate_envelope(evt: dict[str, Any]) -> list[str]:
    """Return a list of problems ([] = valid). Uses jsonschema if available."""
    errors: list[str] = []
    required = ("contract", "event_id", "occurred_at", "tenant_id", "source", "domain", "type", "payload")
    for f in required:
        if f not in evt:
            errors.append(f"missing field '{f}'")
    if errors:
        return errors
    if evt["contract"] not in ACCEPTED_CONTRACTS:
        errors.append(f"contract {evt['contract']} not in {sorted(ACCEPTED_CONTRACTS)}")
    if evt["domain"] not in DOMAINS:
        errors.append(f"unknown domain '{evt['domain']}'")
    if evt["type"] not in TYPES:
        errors.append(f"unknown type '{evt['type']}'")
    if evt["source"] not in SOURCES:
        errors.append(f"source must be one of {sorted(SOURCES)}, got '{evt['source']}'")
    # Provide-direction types must come from admin and match their domain.
    if evt["type"] in _PROVIDE_TYPES:
        if evt["source"] != "admin":
            errors.append(f"type '{evt['type']}' must have source 'admin'")
        if evt["domain"] != _PROVIDE_TYPES[evt["type"]]:
            errors.append(f"type '{evt['type']}' must be in domain '{_PROVIDE_TYPES[evt['type']]}'")
    try:
        assert_phi_free(evt["payload"])
    except ValueError as e:
        errors.append(str(e))
    # Optional full schema check when the schemas + jsonschema are present.
    try:
        import jsonschema  # type: ignore
        schema = _load_schema(evt["domain"])
        if schema is not None:
            try:
                jsonschema.validate(evt, schema)
            except jsonschema.ValidationError as e:  # pragma: no cover
                errors.append(f"schema: {e.message}")
    except ImportError:
        pass
    return errors


_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "contracts" / "schemas"
_SCHEMA_FILE = {"session": "session_event.schema.json", "reporting": "reporting_record.schema.json"}


def _load_schema(domain: str) -> dict | None:
    name = _SCHEMA_FILE.get(domain)
    if not name:
        return None
    p = _SCHEMA_DIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def sign(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature for a webhook body (hex). Header: X-Hub-Signature."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, secret: str, signature: str) -> bool:
    return hmac.compare_digest(sign(body, secret), signature or "")
