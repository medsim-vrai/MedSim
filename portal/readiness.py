"""portal/readiness.py — FR-011 G2: readiness / health as a service.

ONE call the mission-control GUI (G3+) polls to render its readiness bar + the
Setup ecosystem board: a list of checks, each green / amber / red with a detail
line and any one-tap actions. Wraps the preflight.sh / cert-doctor logic in
Python (so the GUI doesn't shell out) plus the portal / storage / vault /
session / device health the portal already exposes piecemeal.

All imports are lazy (this module is imported by server.py) and every check is
wrapped so one failure never breaks the snapshot.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

GREEN, AMBER, RED = "green", "amber", "red"
_CERT_PATH = Path(__file__).parent / "data" / "certs" / "dev-cert.pem"


def _check(cid: str, label: str, status: str, detail: str,
           actions: list[dict] | None = None) -> dict[str, Any]:
    return {"id": cid, "label": label, "status": status,
            "detail": detail, "actions": actions or []}


def _lan_ip() -> str:
    try:
        from .server import _lan_ip as _srv_lan_ip
        return _srv_lan_ip() or ""
    except Exception:  # noqa: BLE001
        return ""


# ── individual checks ────────────────────────────────────────────────────────

def _portal() -> dict[str, Any]:
    return _check("portal", "Portal", GREEN, "Operator portal is running.")


def _network() -> dict[str, Any]:
    bind = (os.environ.get("MEDSIM_HOST") or "127.0.0.1").strip()
    if bind in ("127.0.0.1", "localhost", "::1"):
        return _check("network", "Network", AMBER,
                      "Bound to loopback — tablets on the Wi-Fi can't reach the portal. "
                      "Relaunch with MEDSIM_HOST=0.0.0.0.")
    ip = _lan_ip()
    host = (os.environ.get("MEDSIM_PUBLIC_HOST") or "").strip()
    detail = f"LAN IP {ip or 'unknown'}" + (f" · name {host}" if host else "")
    return _check("network", "Network", GREEN if ip else AMBER, detail)


def _cert_sans() -> list[str]:
    try:
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(_CERT_PATH.read_bytes())
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
        out: list[str] = []
        for entry in san:
            try:
                out.append(str(entry.value))
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception:  # noqa: BLE001
        return []


def _cert() -> dict[str, Any]:
    if not _CERT_PATH.is_file():
        return _check("cert", "TLS certificate", RED,
                      "No dev cert — tablets get a 'not secure' warning. Generate one "
                      "(scripts/dev_cert.py) and restart.")
    ip = _lan_ip()
    sans = _cert_sans()
    san_str = ", ".join(sans) or "?"
    if ip and ip not in sans:
        return _check("cert", "TLS certificate", AMBER,
                      f"Cert SAN does not cover {ip} (SAN: {san_str}). Re-mint the LEAF "
                      f"for this IP (NEVER re-mint the CA) and restart: "
                      f"python scripts/dev_cert.py {ip}")
    return _check("cert", "TLS certificate", GREEN,
                  f"Covers {ip or 'the LAN IP'} (SAN: {san_str}).")


def _storage() -> dict[str, Any]:
    from . import ehr_db
    st = ehr_db.storage_status()
    if st.get("durable"):
        return _check("storage", "Persistence", GREEN,
                      f"Durable SQLite (schema v{st.get('schema_version')}).")
    return _check("storage", "Persistence", RED,
                  ("DEGRADED — in-memory only; data is LOST on restart. "
                   + str(st.get("degraded_reason") or "")).strip())


def _vault() -> dict[str, Any]:
    try:
        from . import credentials
        init = credentials.is_initialized()
    except Exception:  # noqa: BLE001
        init = False
    return _check("vault", "Credential vault", GREEN if init else AMBER,
                  "Vault initialized." if init else
                  "Vault not initialized — log in to unlock provider keys.")


def _session() -> dict[str, Any]:
    from . import control_session, session_state
    try:
        active = control_session.get_active()
    except Exception:  # noqa: BLE001
        active = None
    if active is not None:
        return _check("session", "Control session", GREEN,
                      f"Active: {getattr(active, 'scenario_name', '') or active.id}.")
    snap = None
    try:
        snap = session_state.load_latest()
    except Exception:  # noqa: BLE001
        snap = None
    if snap:
        encs = (snap.get("control_session") or {}).get("encounters") or []
        names = ", ".join(e.get("scenario_name", "") for e in encs if isinstance(e, dict))
        return _check("session", "Control session", AMBER,
                      f"No active session — a saved one can resume ({names or 'prior session'}).",
                      [{"id": "resume_session", "label": "Resume last session", "kind": "run"}])
    return _check("session", "Control session", AMBER,
                  "No active session — configure one in Setup.")


def _devices() -> dict[str, Any]:
    from . import control_session, ehr_db
    try:
        active = control_session.get_active()
    except Exception:  # noqa: BLE001
        active = None
    if active is None:
        return _check("devices", "Devices", AMBER, "No active session — no devices yet.")
    stations = ehr_db.device_stations(active.id) or []
    n = len(stations)
    return _check("devices", "Devices", GREEN if n else AMBER,
                  f"{n} device station(s) registered." if n
                  else "No devices joined yet — mint a QR in Setup.")


_CHECKS = (_portal, _network, _cert, _storage, _vault, _session, _devices)


def snapshot() -> dict[str, Any]:
    """The full readiness snapshot: each check + a rolled-up overall status."""
    checks: list[dict[str, Any]] = []
    for fn in _CHECKS:
        try:
            checks.append(fn())
        except Exception:  # noqa: BLE001 — one bad check never breaks the bar
            log.debug("readiness: check %s failed", getattr(fn, "__name__", "?"),
                      exc_info=True)
    statuses = {c["status"] for c in checks}
    overall = RED if RED in statuses else (AMBER if AMBER in statuses else GREEN)
    return {"overall": overall, "checks": checks}


# ── executable actions (POST /api/control/readiness/action {id}) ─────────────

def _act_resume_session() -> dict[str, Any]:
    from . import session_state
    summary = session_state.resume()
    return {"ok": bool(summary), "summary": summary}


_ACTIONS: dict[str, Callable[[], dict[str, Any]]] = {
    "resume_session": _act_resume_session,
}


def run_action(action_id: str) -> dict[str, Any]:
    """Run a one-tap readiness action. Info-only actions (cert/network fixes are
    operator/sudo steps) are NOT here — only safe in-process ones."""
    fn = _ACTIONS.get(action_id)
    if fn is None:
        return {"ok": False, "error": f"unknown or non-executable action {action_id!r}"}
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
