"""portal/readiness.py — FR-011 G2: readiness / health as a service.

ONE call the mission-control GUI (G3+) polls to render its readiness bar + the
Setup ecosystem board: a list of checks, each green / amber / red with a detail
line and any one-tap actions. Wraps the preflight.sh / cert-doctor logic in
Python (so the GUI doesn't shell out) plus the portal / network / cert / voice /
speech / storage / EHR / vault / session / device health the portal already
exposes piecemeal.

Every check takes the (optional) authenticated Vault the route already holds —
checks that need stored provider keys use it; the rest ignore it, so snapshot()
is still callable with no vault (tests / CLI). All other imports are lazy (this
module is imported by server.py) and every check is wrapped so one failure never
breaks the snapshot.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

GREEN, AMBER, RED = "green", "amber", "red"
_CERT_PATH = Path(__file__).parent / "data" / "certs" / "dev-cert.pem"

# FR-128 — Anthropic key VERDICT: the cheapest correct signal of key health for the
# Operate readiness bar, WITHOUT calling Anthropic on every poll. Live character
# turns and the credentials "Test" button already learn the truth (auth error vs
# success); they record it here, and _voice reflects it. "unknown" = set but never
# exercised (stays green — matches prior behavior); a fresh key save resets it.
_key_verdict: dict[str, Any] = {"state": "unknown", "detail": ""}


def note_key_ok() -> None:
    _key_verdict.update(state="ok", detail="")


def note_key_rejected(detail: str = "") -> None:
    _key_verdict.update(state="rejected", detail=(detail or "").strip()[:160])


def note_key_changed() -> None:
    """A new key was saved — forget the old verdict until it's exercised again."""
    _key_verdict.update(state="unknown", detail="")

# The documented graceful-restart command (G7 resumes the session on boot).
# Restart is ALWAYS an operator action — the GUI detects + resumes, never self-restarts.
_RESTART_HINT = ("pkill -TERM -f run_portal.py  &&  "
                 "MEDSIM_NO_BROWSER=1 MEDSIM_HOST=0.0.0.0 .venv/bin/python run_portal.py")


def _check(cid: str, label: str, status: str, detail: str,
           actions: list[dict] | None = None) -> dict[str, Any]:
    return {"id": cid, "label": label, "status": status,
            "detail": detail, "actions": actions or []}


def _action(aid: str, label: str) -> dict[str, str]:
    return {"id": aid, "label": label, "kind": "run"}


def _lan_ip() -> str:
    try:
        from .server import _lan_ip as _srv_lan_ip
        return _srv_lan_ip() or ""
    except Exception:  # noqa: BLE001
        return ""


# ── individual checks (uniform (vault) signature; unused arg is fine) ─────────

def _portal(vault: Any = None) -> dict[str, Any]:
    return _check("portal", "Portal", GREEN, "Operator portal is running.")


def _network(vault: Any = None) -> dict[str, Any]:
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


def _cert(vault: Any = None) -> dict[str, Any]:
    if not _CERT_PATH.is_file():
        return _check("cert", "TLS certificate", RED,
                      "No dev cert — tablets get a 'not secure' warning. Generate one "
                      "(scripts/dev_cert.py) and restart.",
                      [_action("recheck_cert", "Re-check certificate")])
    ip = _lan_ip()
    sans = _cert_sans()
    san_str = ", ".join(sans) or "?"
    if ip and ip not in sans:
        return _check("cert", "TLS certificate", AMBER,
                      f"Cert SAN does not cover {ip} (SAN: {san_str}). Re-mint the LEAF "
                      f"for this IP (NEVER re-mint the CA) and restart: "
                      f"python scripts/dev_cert.py {ip}",
                      [_action("recheck_cert", "Re-check certificate")])
    return _check("cert", "TLS certificate", GREEN,
                  f"Covers {ip or 'the LAN IP'} (SAN: {san_str}).")


def _voice(vault: Any = None) -> dict[str, Any]:
    """Can characters talk? Anthropic key drives replies (blocking if absent);
    ElevenLabs is optional (browser-TTS fallback). Needs the unlocked vault."""
    if vault is None:
        return _check("voice", "Voice / AI", AMBER,
                      "Log in to verify the AI + voice provider keys.")
    stored = getattr(vault, "credentials", {}) or {}
    if not stored.get("ANTHROPIC_API_KEY"):
        return _check("voice", "Voice / AI", RED,
                      "No Anthropic API key — characters can't generate replies. "
                      "Add it in Setup → credentials.")
    tts = "ElevenLabs TTS" if stored.get("ELEVENLABS_API_KEY") \
        else "browser TTS (no ElevenLabs key)"
    # FR-128 — reflect what live turns / the Test button learned, so the cockpit
    # warns BEFORE a character does. A rejected key is RED even though one is set.
    if _key_verdict["state"] == "rejected":
        d = _key_verdict["detail"] or "the last character turn was refused"
        return _check("voice", "Voice / AI", RED,
                      f"Anthropic key was REJECTED ({d}) — update it in credentials.")
    verified = " (verified)" if _key_verdict["state"] == "ok" else ""
    return _check("voice", "Voice / AI", GREEN, f"Anthropic key set{verified} · {tts}.")


def _speech(vault: Any = None) -> dict[str, Any]:
    """Room-local STT (FR-006b) — only needed for audio stations, so cold is
    amber (warm it), not red."""
    from . import room_stt
    if getattr(room_stt, "_engine", None) is not None:
        return _check("speech", "Speech-to-text", GREEN, "Room STT model is warm.")
    warm = [_action("warm_speech", "Warm speech model")]
    err = getattr(room_stt, "_engine_err", None)
    if err:
        return _check("speech", "Speech-to-text", AMBER,
                      f"STT model failed to load: {err}. Warm to retry.", warm)
    return _check("speech", "Speech-to-text", AMBER,
                  "STT model cold — warm it before audio stations transcribe.", warm)


def _storage(vault: Any = None) -> dict[str, Any]:
    from . import ehr_db
    st = ehr_db.storage_status()
    if st.get("durable"):
        return _check("storage", "Persistence", GREEN,
                      f"Durable SQLite (schema v{st.get('schema_version')}).")
    return _check("storage", "Persistence", RED,
                  ("DEGRADED — in-memory only; data is LOST on restart. "
                   + str(st.get("degraded_reason") or "")).strip())


def _ehr(vault: Any = None) -> dict[str, Any]:
    """Is an EHR selected for the active session? (Durability is _storage's job.)"""
    from . import control_session
    try:
        active = control_session.get_active()
    except Exception:  # noqa: BLE001
        active = None
    if active is None:
        return _check("ehr", "EHR", AMBER, "No active session.")
    if not getattr(active, "ehr_id", None):
        return _check("ehr", "EHR", AMBER, "No EHR selected — pick one in Setup.")
    return _check("ehr", "EHR", GREEN, f"EHR '{active.ehr_id}' selected.")


def _vault(vault: Any = None) -> dict[str, Any]:
    try:
        from . import credentials
        init = credentials.is_initialized()
    except Exception:  # noqa: BLE001
        init = False
    return _check("vault", "Credential vault", GREEN if init else AMBER,
                  "Vault initialized." if init else
                  "Vault not initialized — log in to unlock provider keys.")


def _session(vault: Any = None) -> dict[str, Any]:
    from . import control_session, session_state
    try:
        active = control_session.get_active()
    except Exception:  # noqa: BLE001
        active = None
    if active is not None:
        chk = _check("session", "Control session", GREEN,
                     f"Active: {getattr(active, 'scenario_name', '') or active.id}.")
        # FR-011 G7 — if this session was auto-restored on boot (or via Resume),
        # confirm it so the operator trusts the restore + sees how fresh it is.
        try:
            lr = session_state.last_resume()
        except Exception:  # noqa: BLE001
            lr = None
        if lr and lr.get("saved_at"):
            import time as _t
            hhmm = _t.strftime("%H:%M", _t.localtime(lr["saved_at"]))
            names = ", ".join(n for n in (lr.get("names") or []) if n) or "last session"
            chk["detail"] = f"Resumed '{names}' (saved {hhmm})."
            chk["resumed"] = True
            chk["saved_at"] = lr["saved_at"]
        return chk
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
                      [_action("resume_session", "Resume last session")])
    return _check("session", "Control session", AMBER,
                  "No active session — configure one in Setup.")


def _devices(vault: Any = None) -> dict[str, Any]:
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


_CHECKS: tuple[Callable[..., dict[str, Any]], ...] = (
    _portal, _network, _cert, _voice, _speech, _storage, _ehr, _vault, _session, _devices,
)


def snapshot(vault: Any = None) -> dict[str, Any]:
    """The full readiness snapshot: each check + a worst-of rolled-up overall."""
    checks: list[dict[str, Any]] = []
    for fn in _CHECKS:
        try:
            checks.append(fn(vault))
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


def _act_warm_speech() -> dict[str, Any]:
    from . import room_stt
    room_stt.warm_in_background()
    return {"ok": True, "detail": "Warming the room STT model in the background."}


def _act_recheck_cert() -> dict[str, Any]:
    # The cert is read fresh on every snapshot — the route re-attaches one, so this
    # just acknowledges; the refreshed `cert` check reflects the current SAN.
    return {"ok": True, "detail": "Re-read the TLS certificate."}


def _act_restart_hint() -> dict[str, Any]:
    # NEVER restarts the portal — restart is an operator action; the GUI resumes (G7).
    return {"ok": True, "hint": _RESTART_HINT,
            "detail": "Run this in the portal's terminal; the session resumes on boot."}


def _act_test_all() -> dict[str, Any]:
    # The route re-attaches a fresh snapshot to every action result, so "test all"
    # is simply that re-run. Warm speech opportunistically so the next poll is green.
    from . import room_stt
    try:
        if getattr(room_stt, "_engine", None) is None:
            room_stt.warm_in_background()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "detail": "Re-ran all checks."}


_ACTIONS: dict[str, Callable[[], dict[str, Any]]] = {
    "resume_session": _act_resume_session,
    "warm_speech": _act_warm_speech,
    "recheck_cert": _act_recheck_cert,
    "restart_hint": _act_restart_hint,
    "test_all": _act_test_all,
}


def run_action(action_id: str) -> dict[str, Any]:
    """Run a one-tap readiness action. Side-effecting OS steps (cert re-mint,
    portal restart) stay info-only — only safe in-process actions execute here."""
    fn = _ACTIONS.get(action_id)
    if fn is None:
        return {"ok": False, "error": f"unknown or non-executable action {action_id!r}"}
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
