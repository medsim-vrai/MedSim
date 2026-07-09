"""High-level emit API for V8. Every emit ENQUEUES to the durable spool (never
blocks the caller, works offline) and opportunistically replays. No-op when the
adapter is disabled. Call from existing V8 hooks (ControlRoom lifecycle, debrief
save, budget charge, auth events)."""
from __future__ import annotations
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import config, contract, mappers
from .queue import Spool

_spool = Spool(config.QUEUE_DIR)
# Single background worker for spool replay (EMIT_ASYNC). One worker serializes replays so two
# drains can never double-send the same spooled event; the durable enqueue happens BEFORE we submit,
# so the newly-enqueued event is always caught by the replay we kick.
_replay_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hub-emit")


def _online_sender(evt: dict[str, Any]) -> bool:
    """Signed POST to the hub. Returns False on any failure so the spool keeps the event."""
    if not config.ENABLED:
        return False
    try:
        body = json.dumps(evt, separators=(",", ":")).encode()
        sig = contract.sign(body, config.HUB_SIGNING_KEY)
        req = urllib.request.Request(f"{config.HUB_BASE_URL}/events", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "X-Hub-Signature": sig,
                                              "X-Hub-Event-Id": evt["event_id"]})
        with urllib.request.urlopen(req, timeout=config.TIMEOUT_S,
                                    context=config.ssl_context()) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _emit(evt: dict[str, Any]) -> None:
    if not config.ENABLED:
        return
    _spool.enqueue(evt)                # durable first — survives a crash mid-flight
    if config.EMIT_ASYNC:
        _replay_pool.submit(_spool.replay, _online_sender)  # background: never blocks the caller
    else:
        _spool.replay(_online_sender)  # inline best-effort flush (legacy; offline leaves it queued)


def flush() -> int:
    """Replay anything queued (call on reconnect / startup / a timer)."""
    return _spool.replay(_online_sender)


def queue_depth() -> int:
    return _spool.depth()


# --- public emitters ---
def session_started(*, session_id: str, **kw: Any) -> None:
    _emit(mappers.session_event(type="session.started", session_id=session_id, **kw))

def session_paused(*, session_id: str, **kw: Any) -> None:
    _emit(mappers.session_event(type="session.paused", session_id=session_id, **kw))

def session_resumed(*, session_id: str, **kw: Any) -> None:
    _emit(mappers.session_event(type="session.resumed", session_id=session_id, **kw))

def session_ended(*, session_id: str, **kw: Any) -> None:
    _emit(mappers.session_event(type="session.ended", session_id=session_id, **kw))

def report_completed(*, record: dict[str, Any], **kw: Any) -> None:
    _emit(mappers.reporting_record(record=record, **kw))

def usage(*, metric: str, **kw: Any) -> None:
    _emit(mappers.metering_turn(metric=metric, **kw))

def audit(*, actor: str, action: str, **kw: Any) -> None:
    _emit(mappers.audit_event(actor=actor, action=action, **kw))
