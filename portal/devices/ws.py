"""WebSocket connection manager + endpoints for the device subsystem.

There are two roles:

- ``device`` — one connection per joined DeviceStation. Sends ``event``
  messages (student actions, heartbeats) and receives ``inject``,
  ``assign``, ``state`` messages broadcast by the server.
- ``instructor`` — one or more connections per operator UI. Receives a
  firehose of every device event in the active session so the roster and
  detail panels stay live without polling.

State invariant: nothing in the WebSocket layer is the system of record.
Every state-changing event is persisted via the engine first; the WS
broadcasts the persisted row so reconnecting clients can re-fold from
``ehr_db.device_events`` and converge.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from portal import control_session, ehr_db
from portal.devices import registry
from portal.devices.engine.state_machine import make_engine


class ConnectionManager:
    def __init__(self) -> None:
        # station_id → device-side socket
        self._devices: dict[str, WebSocket] = {}
        # instructor sockets keyed by id(ws) so we can remove cleanly
        self._instructors: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_device(self, station_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            # Bump any previous connection for this station — last writer wins.
            prev = self._devices.get(station_id)
            if prev is not None:
                try:
                    await prev.close()
                except Exception:
                    pass
            self._devices[station_id] = ws

    async def disconnect_device(self, station_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if self._devices.get(station_id) is ws:
                self._devices.pop(station_id, None)

    async def connect_instructor(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._instructors.add(ws)

    async def disconnect_instructor(self, ws: WebSocket) -> None:
        async with self._lock:
            self._instructors.discard(ws)

    async def send_to_device(self, station_id: str, message: dict[str, Any]) -> None:
        ws = self._devices.get(station_id)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            await self.disconnect_device(station_id, ws)

    async def broadcast_to_instructors(self, message: dict[str, Any]) -> None:
        if not self._instructors:
            return
        dead: list[WebSocket] = []
        text = json.dumps(message)
        async with self._lock:
            targets = list(self._instructors)
        for ws in targets:
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_text(text)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._instructors.discard(ws)

    async def broadcast_state(self, state: str) -> None:
        """Push a global pause/resume to every connected device."""
        async with self._lock:
            stations = list(self._devices.keys())
        for sid in stations:
            await self.send_to_device(sid, {"type": "state", "state": state})


manager = ConnectionManager()


async def handle_device_ws(ws: WebSocket, station_id: str) -> None:
    station = ehr_db.get_device_station(station_id)
    if station is None:
        await ws.close(code=1008)   # policy violation
        return
    sess = control_session.get_active()
    if sess is None or sess.id != station["session_id"]:
        await ws.close(code=1008)
        return
    await manager.connect_device(station_id, ws)
    ehr_db.touch_device_station(station_id)
    # V6 — also update the in-memory DeviceStation.last_seen. The roster's
    # online dot reads from this in-memory object, not from SQLite, so
    # without this update the operator's roster card flips to offline
    # after 45s even while the device is actively heartbeating over WS.
    # Self-heal: if the in-memory entry is missing (e.g. operator opened
    # the page mid-session), rehydrate it from the persisted DB row.
    if station_id not in sess.device_stations:
        sess.add_device_station(
            station_id,
            device_kind=station["device_kind"],
            device_model=station["device_model"],
            label=station.get("label") or "",
            user_agent=station.get("user_agent") or "",
        )
    sess.device_stations[station_id].touch()
    # Push current ControlSession state so the device can render the right
    # screen (alarm if paused, normal otherwise).
    try:
        await ws.send_text(json.dumps({"type": "state", "state": sess.state}))
        engine = make_engine(session_id=sess.id, station_id=station_id,
                             device_kind=station["device_kind"],
                             device_model=station["device_model"])
        # Initial fold — so a reconnecting device repaints without a separate fetch.
        await ws.send_text(json.dumps({"type": "fold",
                                         "state": engine.fold()}))
    except Exception:
        await manager.disconnect_device(station_id, ws)
        return

    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "event":
                # Reject student input while paused.
                if sess.state == "paused":
                    await ws.send_text(json.dumps(
                        {"type": "rejected", "reason": "paused"}))
                    continue
                ev_type = msg.get("event_type") or msg.get("ev_type")
                payload = msg.get("payload") or {}
                if not ev_type:
                    continue
                engine = make_engine(session_id=sess.id, station_id=station_id,
                                     device_kind=station["device_kind"],
                                     device_model=station["device_model"])
                engine.handle(type=ev_type, surface="device", payload=payload)
                ehr_db.touch_device_station(station_id)
                if station_id in sess.device_stations:
                    sess.device_stations[station_id].touch()
                # Push new fold to the device + firehose to instructors.
                new_state = engine.fold()
                await ws.send_text(json.dumps({"type": "fold", "state": new_state}))
                await manager.broadcast_to_instructors({
                    "type": "device_event", "station_id": station_id,
                    "event_type": ev_type, "payload": payload,
                    "state": new_state,
                })
            elif mtype == "heartbeat":
                ehr_db.touch_device_station(station_id)
                if station_id in sess.device_stations:
                    sess.device_stations[station_id].touch()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_device(station_id, ws)


async def handle_instructor_ws(ws: WebSocket) -> None:
    sess = control_session.get_active()
    if sess is None:
        await ws.close(code=1008)
        return
    await manager.connect_instructor(ws)
    try:
        # Initial roster snapshot.
        roster = []
        for sid, ds in sess.device_stations.items():
            assignment = ehr_db.current_assignment(sid)
            roster.append({
                "station_id": sid, "device_kind": ds.device_kind,
                "device_model": ds.device_model, "label": ds.label,
                "online": ds.online, "runtime_state": ds.runtime_state,
                "character_id": (assignment or {}).get("character_id"),
            })
        await ws.send_text(json.dumps({"type": "roster", "stations": roster}))
        while True:
            text = await ws.receive_text()
            # Instructor side is mostly read-only over WS; the inject /
            # assign actions go through the HTTP routes for auth gating.
            # We accept ping messages for connection keep-alive.
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_instructor(ws)
