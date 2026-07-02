"""Encrypted credential vault for the medsim portal.

Vault file: ``~/.medsim/vault.enc`` (cross-platform via ``Path.home()``).
Encryption: Fernet (AES-128-CBC + HMAC) with a key derived from the master
password via PBKDF2-HMAC-SHA256 at 600k iterations (OWASP 2023+).

The vault never persists the master password — only a salt and an encrypted
verifier token. A bad password fails to decrypt the verifier, which is how we
distinguish a wrong password from data corruption.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VAULT_DIR = Path.home() / ".medsim"
VAULT_PATH = VAULT_DIR / "vault.enc"
VERIFIER_PLAINTEXT = b"medsim_v1"
PBKDF2_ITERATIONS = 600_000


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def is_initialized() -> bool:
    return VAULT_PATH.exists()


def initialize(password: str) -> None:
    """Create a new empty vault. Raises if one already exists."""
    if is_initialized():
        raise FileExistsError("Vault already initialized")
    if len(password) < 8:
        raise ValueError("Master password must be at least 8 characters")
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    payload = {
        "version": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "verifier": fernet.encrypt(VERIFIER_PLAINTEXT).decode("ascii"),
        "credentials": fernet.encrypt(b"{}").decode("ascii"),
    }
    VAULT_PATH.write_text(json.dumps(payload, indent=2))
    try:
        os.chmod(VAULT_PATH, 0o600)
    except OSError:
        pass  # no-op on Windows


@dataclass
class Vault:
    _key: bytes
    _data: dict[str, str] = field(default_factory=dict)

    @property
    def credentials(self) -> dict[str, str]:
        return dict(self._data)

    def get(self, name: str) -> str | None:
        return self._data.get(name)

    def set(self, name: str, value: str) -> None:
        self._data[name] = value
        self._persist()

    def delete(self, name: str) -> None:
        self._data.pop(name, None)
        self._persist()

    def _persist(self) -> None:
        raw = json.loads(VAULT_PATH.read_text())
        fernet = Fernet(self._key)
        raw["credentials"] = fernet.encrypt(
            json.dumps(self._data).encode("utf-8")
        ).decode("ascii")
        VAULT_PATH.write_text(json.dumps(raw, indent=2))


def unlock(password: str) -> Vault:
    """Decrypt and return the vault. Raises ValueError on bad password."""
    if not is_initialized():
        raise FileNotFoundError("Vault not initialized")
    raw = json.loads(VAULT_PATH.read_text())
    salt = base64.b64decode(raw["salt"])
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    try:
        if fernet.decrypt(raw["verifier"].encode("ascii")) != VERIFIER_PLAINTEXT:
            raise ValueError("Invalid master password")
        data = json.loads(fernet.decrypt(raw["credentials"].encode("ascii")))
    except InvalidToken as e:
        raise ValueError("Invalid master password") from e
    return Vault(_key=key, _data=data)


# ── Per-seat passwords (task #94 — real credential separation) ─────────────
#
# The MASTER password stays the 'admin' seat (it owns the vault today, so a
# legacy vault keeps working unchanged — no lockout, no migration step). Each
# lesser seat can get its OWN password: an envelope entry wrapping the master
# Fernet key with a key derived from that seat's password. Which password
# unlocks IS the seat — the login form's radio can only lower privilege.
# Additive format: vaults without "role_keys" behave exactly as before.

ROLE_PASSWORD_SEATS = ("instructor", "observer")


def set_role_password(vault: Vault, role: str, password: str) -> None:
    """Give `role` its own password (admin-gated at the route). The stored entry
    wraps the master key, so this seat's password opens the same vault data."""
    if role not in ROLE_PASSWORD_SEATS:
        raise ValueError(f"No per-seat password for role: {role}")
    if len(password) < 8:
        raise ValueError("Seat password must be at least 8 characters")
    raw = json.loads(VAULT_PATH.read_text())
    salt = secrets.token_bytes(16)
    role_fernet = Fernet(_derive_key(password, salt))
    raw.setdefault("role_keys", {})[role] = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "wrapped": role_fernet.encrypt(vault._key).decode("ascii"),
    }
    VAULT_PATH.write_text(json.dumps(raw, indent=2))


def clear_role_password(role: str) -> None:
    raw = json.loads(VAULT_PATH.read_text())
    if raw.get("role_keys", {}).pop(role, None) is not None:
        VAULT_PATH.write_text(json.dumps(raw, indent=2))


def role_passwords_set() -> dict[str, bool]:
    """Which seats have their own password (for the credentials page)."""
    if not is_initialized():
        return {r: False for r in ROLE_PASSWORD_SEATS}
    raw = json.loads(VAULT_PATH.read_text())
    have = raw.get("role_keys", {})
    return {r: r in have for r in ROLE_PASSWORD_SEATS}


def unlock_role(password: str) -> tuple[Vault, str]:
    """Unlock with ANY seat's password → (vault, seat). The master password is
    the 'admin' seat; a per-seat password yields that seat. Raises ValueError
    when no credential matches (indistinguishable from a wrong password)."""
    try:
        return unlock(password), "admin"
    except ValueError:
        pass
    raw = json.loads(VAULT_PATH.read_text())
    for role, entry in (raw.get("role_keys") or {}).items():
        role_key = _derive_key(password, base64.b64decode(entry["salt"]))
        try:
            master_key = Fernet(role_key).decrypt(entry["wrapped"].encode("ascii"))
        except InvalidToken:
            continue
        fernet = Fernet(master_key)
        data = json.loads(fernet.decrypt(raw["credentials"].encode("ascii")))
        return Vault(_key=master_key, _data=data), role
    raise ValueError("Invalid password")
