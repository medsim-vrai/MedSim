"""Session management for the medsim portal.

Single-instructor model. The decrypted vault is held in process memory keyed
by an opaque session token; the cookie sent to the browser carries only a
signed copy of that token (via itsdangerous). Server restart clears all
sessions and forces re-login.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, TimestampSigner

from . import credentials as cred_module

SESSION_TTL_SECONDS = 8 * 60 * 60
COOKIE_NAME = "medsim_session"
_SIGNER_KEY_FILE = Path.home() / ".medsim" / "session.key"
_active_vaults: dict[str, cred_module.Vault] = {}
# V7 M18 — role per session token. 'instructor' (default, full read+write),
# 'admin' (FR — full read+write, same powers as instructor for now; a label +
# landing distinction until real credential separation lands, see
# docs/SECURITY-auth-rollout.md), or 'observer' (read-only TA / preceptor seat).
_session_roles: dict[str, str] = {}
_VALID_ROLES = ("instructor", "admin", "observer")


def _signer() -> TimestampSigner:
    if not _SIGNER_KEY_FILE.exists():
        _SIGNER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SIGNER_KEY_FILE.write_bytes(secrets.token_bytes(32))
        try:
            _SIGNER_KEY_FILE.chmod(0o600)
        except OSError:
            pass
    return TimestampSigner(_SIGNER_KEY_FILE.read_bytes())


def issue_session_token(vault: cred_module.Vault,
                          *, role: str = "instructor") -> str:
    """Issue a session cookie. ``role`` is 'instructor' (default — full
    read+write), 'admin' (full read+write — same powers as instructor for now,
    just a label/landing distinction), or 'observer' (M18 — read-only)."""
    token_id = secrets.token_urlsafe(16)
    signed = _signer().sign(token_id.encode("ascii")).decode("ascii")
    _active_vaults[signed] = vault
    _session_roles[signed] = role if role in _VALID_ROLES else "instructor"
    return signed


def verify_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        _signer().unsign(token, max_age=SESSION_TTL_SECONDS)
        return True
    except BadSignature:
        return False


def clear_session(token: str | None) -> None:
    if token:
        _active_vaults.pop(token, None)
        _session_roles.pop(token, None)


def session_role(token: str | None) -> str:
    """M18 — Return the session's role ('instructor', 'admin', or 'observer').
    Defaults to 'instructor' if unset (matches v6 single-role model)."""
    if not token:
        return "instructor"
    return _session_roles.get(token, "instructor")


def is_admin(token: str | None) -> bool:
    """Whether this session signed in as admin (label only for now)."""
    return session_role(token) == "admin"


def require_vault(
    medsim_session: Annotated[str | None, Cookie()] = None,
) -> cred_module.Vault:
    if not verify_session(medsim_session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required"
        )
    vault = _active_vaults.get(medsim_session) if medsim_session else None
    if vault is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired; please log in again",
        )
    return vault


def require_instructor(
    medsim_session: Annotated[str | None, Cookie()] = None,
) -> cred_module.Vault:
    """M18 — like require_vault but rejects observer (read-only) sessions with
    403. Instructor AND admin both pass (admin has the same powers for now).
    Use on every state-mutating route (freeze/resume/scene/end/activity-CRUD/
    budget-set/etc.)."""
    vault = require_vault(medsim_session)
    if session_role(medsim_session) == "observer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Observer seat is read-only — sign in as instructor or admin.",
        )
    return vault


def require_admin(
    medsim_session: Annotated[str | None, Cookie()] = None,
) -> cred_module.Vault:
    """Task #94 — like require_vault but ONLY the admin seat passes. Use on
    admin-only surfaces (credential management, EHR admin/purge). The admin
    seat is the vault's master password (or a hub-granted admin identity when
    the adapter flag is on); instructor and observer get 403."""
    vault = require_vault(medsim_session)
    if session_role(medsim_session) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Admin seat required — this page manages credentials/system state. "
                    "Sign out, then sign back in choosing the ADMIN seat (the master "
                    "vault password unlocks it), and retry."),
        )
    return vault
