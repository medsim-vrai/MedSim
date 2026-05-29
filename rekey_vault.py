#!/usr/bin/env python3
"""Reset the medsim master password while preserving saved API keys.

Run from the v6 root:

    ./.venv/bin/python rekey_vault.py

The script prompts twice (old + new) using getpass — neither value is
echoed to the terminal or stored in shell history. The vault file is
re-encrypted in place; the existing credentials dict (Anthropic key,
ElevenLabs key, etc.) is preserved verbatim.

Any active sessions are invalidated: the session.key is rotated so all
logged-in browsers are forced to re-login with the new password.
"""
from __future__ import annotations

import getpass
import json
import secrets
import sys
from pathlib import Path

from portal import credentials


def main() -> int:
    if not credentials.is_initialized():
        print(f"No vault found at {credentials.VAULT_PATH}. Nothing to re-key.",
              file=sys.stderr)
        return 1

    print(f"Vault location: {credentials.VAULT_PATH}")
    old = getpass.getpass("Current master password: ")
    try:
        vault = credentials.unlock(old)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Could not unlock: {exc}", file=sys.stderr)
        return 2

    saved = vault.credentials
    print(f"Vault unlocked. {len(saved)} credential(s) currently stored: "
          f"{sorted(saved.keys()) if saved else '(empty)'}")

    new1 = getpass.getpass("New master password (min 8 chars): ")
    if len(new1) < 8:
        print("New password must be at least 8 characters.", file=sys.stderr)
        return 3
    new2 = getpass.getpass("Confirm new password:            ")
    if new1 != new2:
        print("Passwords did not match.", file=sys.stderr)
        return 4
    if new1 == old:
        print("New password is the same as the old one — nothing to do.",
              file=sys.stderr)
        return 5

    # Re-key: delete + re-initialize + restore credentials.
    credentials.VAULT_PATH.unlink()
    credentials.initialize(new1)
    new_vault = credentials.unlock(new1)
    for name, value in saved.items():
        new_vault.set(name, value)

    # Rotate the session signer key so every logged-in browser is forced
    # to re-login with the new password.
    signer_key = Path.home() / ".medsim" / "session.key"
    if signer_key.exists():
        signer_key.write_bytes(secrets.token_bytes(32))

    print()
    print("✓ Master password reset.")
    print(f"  Credentials preserved: {sorted(saved.keys()) if saved else '(none)'}")
    print(f"  All existing browser sessions invalidated — log in fresh at /login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
