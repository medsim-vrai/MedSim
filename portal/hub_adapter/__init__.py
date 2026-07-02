"""V8 hub adapter — anti-corruption boundary between on-prem MedSim VRAI (V8) and the
admin / integration layer. Offline-tolerant: emits spool to a durable queue and replay
on reconnect. Feature-flagged via HUB_ADAPTER_ENABLED.

Wiring (install to portal/hub_adapter/ in the V8 repo):
  - emit.session_* / report_completed / usage / audit  <- call from existing hooks
  - emit.flush()                                        <- call on startup + a timer (reconnect)
  - consume.identity                                    <- read in auth (cached for offline)
See INSTALL.md."""
from . import config, contract, emit, consume, mappers, queue  # noqa: F401

__all__ = ["config", "contract", "emit", "consume", "mappers", "queue"]
