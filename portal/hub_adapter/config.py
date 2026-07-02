"""V8 hub adapter configuration. Feature-flagged OFF by default. V8 is on-prem and
may be offline, so events are spooled durably and replayed on reconnect."""
from __future__ import annotations
import os
from pathlib import Path

ENABLED = os.getenv("HUB_ADAPTER_ENABLED", "0") == "1"
HUB_BASE_URL = os.getenv("HUB_BASE_URL", "https://hub.internal/api/v0")
HUB_SIGNING_KEY = os.getenv("HUB_SIGNING_KEY", "")
QUEUE_DIR = Path(os.getenv("HUB_QUEUE_DIR", str(Path.home() / ".medsim" / "hub_queue")))
SOURCE = "v8"
CONTRACT = "0.2.0"

# V8 is a "tenant of one"; the local deployment's tenant id (stable).
LOCAL_TENANT_ID = os.getenv("HUB_LOCAL_TENANT_ID", "v8-local")

CAPABILITIES = ["identity.consume", "session.emit", "reporting.emit", "audit.emit"]
TIMEOUT_S = float(os.getenv("HUB_TIMEOUT_S", "5"))
