"""V8 consumes identity from the admin layer when online, and falls back to a local
cache when offline so the on-prem deployment can still authorize during an outage.
V8 is single-tenant, so roster/entitlement consume are optional (the local roster is
authoritative for Studio)."""
from __future__ import annotations
import json
import urllib.request
from pathlib import Path
from typing import Any

from . import config

_CACHE_FILE = config.QUEUE_DIR.parent / "hub_identity_cache.json"


def _read_cache() -> dict[str, Any]:
    try:
        return json.loads(Path(_CACHE_FILE).read_text())
    except Exception:
        return {}


def _write_cache(data: dict[str, Any]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        Path(_CACHE_FILE).write_text(json.dumps(data))
    except Exception:
        pass


def identity(user_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    """Roles + scopes for a user from the admin layer; cached for offline use."""
    if not config.ENABLED:
        return {}
    tid = tenant_id or config.LOCAL_TENANT_ID
    cache = _read_cache()
    try:
        req = urllib.request.Request(f"{config.HUB_BASE_URL}/identity/{user_id}",
                                     headers={"X-Hub-Tenant": tid,
                                              "Authorization": f"Bearer {config.HUB_SERVICE_TOKEN}"})
        with urllib.request.urlopen(req, timeout=config.TIMEOUT_S,
                                    context=config.ssl_context()) as resp:
            val = json.loads(resp.read().decode())
            cache[user_id] = val
            _write_cache(cache)
            return val
    except Exception:
        return cache.get(user_id, {})     # offline: serve last-known; never hard-fail auth
