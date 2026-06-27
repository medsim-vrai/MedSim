"""V7 — Per-room WebSocket transport (M16).

Replaces HTTP-polled `freeze_all` / `resume_all` / `scene_inject`
state propagation with a push channel: every UI surface (chat
station, EHR station, device station, charge-nurse dashboard)
subscribes to `/ws/room/{room_code}` and receives broadcast events
in real time.

Mirrors `portal/devices/ws.py` design — Manager class with
connect / disconnect / broadcast — and reuses its safety
invariants (nothing in the WS layer is the system of record;
events are advisory; the durable state lives in `ehr_db`).

Event envelope on the wire:
  {
    "type":         "freeze_all" | "resume_all" | "end" | "scene"
                     | "encounter_state",
    "ts":           <float seconds since epoch>,
    "room_code":    "<...>",
    "encounter_id": "<...>"   (optional, when event is encounter-scoped)
    "payload":      {...}     (event-specific data)
  }

Client behavior on each type:
  - freeze_all / resume_all / end → station UI shows a banner +
    refreshes its local state from the relevant /api/* endpoint.
  - scene → station refetches the chart_event log (or just appends
    the payload-provided event row).
  - encounter_state → fine-grained encounter state change
    (e.g. paused / running / ended). Reserved for future use.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

# FR-016 — intercom (two-way PTT) lets a client RELAY a whitelisted frame to the
# rest of the room over this otherwise push-only channel. Everything else stays
# discarded (keepalive). The room_code is the access token, same trust model as
# the rest of the channel; a size guard bounds a single relayed frame.
# intercom_state/text = calling indicator + STT caption / typed page (text path).
# rtc_* = WebRTC signaling for the live-voice path (FR-016b): the WS is the
# signaling channel; SDP/ICE carry from/to and clients filter by `to`. The voice
# media itself goes peer-to-peer over WebRTC, NOT through this relay.
# intercom_audio is the legacy MediaRecorder fallback (kept for compatibility).
_RELAY_TYPES = {"intercom_state", "intercom_text", "intercom_audio",
                "rtc_hello", "rtc_offer", "rtc_answer", "rtc_ice", "rtc_bye"}
_MAX_RELAY_BYTES = 1_200_000   # bounds any single relayed frame (SDP/ICE are tiny)


class _RoomManager:
    """Active WebSocket subscribers per room_code. One subscriber
    list per room — anything joined to a room sees every broadcast
    for that room."""

    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}
        # Coarse-grained lock — connect/disconnect/broadcast are infrequent
        # enough that a single lock is fine.
        self._lock = asyncio.Lock()

    async def connect(self, room_code: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._subs.setdefault(room_code.upper(), set()).add(ws)

    async def disconnect(self, room_code: str, ws: WebSocket) -> None:
        async with self._lock:
            bucket = self._subs.get(room_code.upper())
            if bucket and ws in bucket:
                bucket.discard(ws)
                if not bucket:
                    self._subs.pop(room_code.upper(), None)

    def subscriber_count(self, room_code: str) -> int:
        return len(self._subs.get(room_code.upper(), ()))

    async def broadcast(self, room_code: str, message: dict[str, Any]) -> int:
        """Send ``message`` to every subscriber of ``room_code``. Closed
        sockets are pruned silently. Returns the number of successful
        sends (useful for telemetry + tests)."""
        msg = dict(message)
        msg.setdefault("room_code", room_code.upper())
        msg.setdefault("ts", time.time())
        async with self._lock:
            bucket = list(self._subs.get(room_code.upper(), ()))
        dead: list[WebSocket] = []
        sent = 0
        for ws in bucket:
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_json(msg)
                    sent += 1
                else:
                    dead.append(ws)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                live = self._subs.get(room_code.upper())
                if live:
                    for ws in dead:
                        live.discard(ws)
                    if not live:
                        self._subs.pop(room_code.upper(), None)
        return sent


manager = _RoomManager()


# ── Convenience emitters ─────────────────────────────────────────────
# Routes call these instead of touching `manager.broadcast` directly,
# so the envelope shape stays consistent.

async def emit_freeze_all(room_code: str, *, encounter_count: int) -> None:
    await manager.broadcast(room_code, {
        "type": "freeze_all",
        "payload": {"encounter_count": encounter_count},
    })


# M35 — Master "Start all" fires this so every subscribed station can
# transition simultaneously. Distinct from resume_all (which is the
# specific paused → running transition); start_all also fires on the
# very first launch (configured → running).
async def emit_start_all(room_code: str, *, encounter_count: int) -> None:
    await manager.broadcast(room_code, {
        "type": "start_all",
        "payload": {"encounter_count": encounter_count},
    })


# M35 — Per-encounter state changes (start / pause / end of a single
# bed) emit on the same room channel but with an encounter_id so the
# client can filter. Distinct from the room-wide emit_* above.
async def emit_encounter_state(room_code: str, *, encounter_id: str,
                                state: str) -> None:
    await manager.broadcast(room_code, {
        "type":         "encounter_state",
        "encounter_id": encounter_id,
        "payload":      {"state": state},
    })


async def emit_resume_all(room_code: str, *, encounter_count: int) -> None:
    await manager.broadcast(room_code, {
        "type": "resume_all",
        "payload": {"encounter_count": encounter_count},
    })


async def emit_room_end(room_code: str, *, encounter_count: int) -> None:
    await manager.broadcast(room_code, {
        "type": "end",
        "payload": {"encounter_count": encounter_count},
    })


async def emit_scene(room_code: str, *, encounter_id: str,
                      scene: dict[str, Any],
                      result: dict[str, Any]) -> None:
    await manager.broadcast(room_code, {
        "type":         "scene",
        "encounter_id": encounter_id,
        "payload":      {"scene": scene, "result": result},
    })


# ── WebSocket endpoint ────────────────────────────────────────────────

async def handle_room_ws(ws: WebSocket, room_code: str) -> None:
    """Accept the connection, hold it open, and disconnect cleanly on
    close. The client sends nothing — this is a one-way push channel.
    A future extension could let the operator's instructor seat send
    presence pings."""
    await manager.connect(room_code, ws)
    try:
        # Keepalive loop — read client frames. Whitelisted intercom frames
        # (FR-016) are RELAYED to the rest of the room; everything else is
        # discarded. Without this loop, disconnects only fire when we try to
        # send and the socket is closed. The receive cancels on disconnect.
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                break
            if not raw or len(raw) > _MAX_RELAY_BYTES:
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(msg, dict) and msg.get("type") in _RELAY_TYPES:
                # Re-broadcast to the room; client-side routing (by `from` /
                # `scope` / `encounter_id`) decides who actually plays it, so
                # the sender naturally ignores its own echo.
                await manager.broadcast(room_code, msg)
    finally:
        await manager.disconnect(room_code, ws)
