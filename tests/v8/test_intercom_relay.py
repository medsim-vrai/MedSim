"""FR-016 — the per-room WS now RELAYS whitelisted intercom frames (live PTT)
while still discarding everything else. These tests pin that relay behavior +
room isolation; the audio capture/playback is browser-side (manual verify)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("MEDSIM_RESUME", "0")
    from portal import server
    with TestClient(server.app) as c:
        yield c


def test_relays_intercom_text_to_the_room(client):
    with client.websocket_connect("/ws/room/ROOMX") as a, \
         client.websocket_connect("/ws/room/ROOMX") as b:
        a.send_json({"type": "intercom_text", "from": "nurse", "scope": "all",
                     "text": "Code team to room 3", "label": "Nursing station"})
        m = b.receive_json()
        assert m["type"] == "intercom_text"
        assert m["from"] == "nurse" and m["scope"] == "all"
        assert m["text"] == "Code team to room 3" and m["label"] == "Nursing station"
        assert m["room_code"] == "ROOMX"          # broadcast stamps the room


def test_relays_bed_talkback_and_state(client):
    with client.websocket_connect("/ws/room/ROOMT") as a, \
         client.websocket_connect("/ws/room/ROOMT") as b:
        a.send_json({"type": "intercom_state", "from": "bed",
                     "encounter_id": "E1", "on": True})
        m = b.receive_json()
        assert m["type"] == "intercom_state" and m["from"] == "bed"
        assert m["encounter_id"] == "E1" and m["on"] is True


def test_relays_intercom_audio(client):
    # "Radio" mode — the real voice rides as a base64 WAV clip on intercom_audio.
    with client.websocket_connect("/ws/room/ROOMA") as a, \
         client.websocket_connect("/ws/room/ROOMA") as b:
        a.send_json({"type": "intercom_audio", "from": "bed", "encounter_id": "E1",
                     "fmt": "wav", "data": "UklGRg=="})
        m = b.receive_json()
        assert m["type"] == "intercom_audio" and m["from"] == "bed"
        assert m["fmt"] == "wav" and m["data"] == "UklGRg=="


def test_relays_rtc_signaling(client):
    # FR-016b — WebRTC signaling (hello/offer/answer/ice) rides the room WS,
    # addressed by `to`; the relay rebroadcasts and clients filter.
    with client.websocket_connect("/ws/room/ROOMR") as a, \
         client.websocket_connect("/ws/room/ROOMR") as b:
        a.send_json({"type": "rtc_offer", "from": "bed:E1", "to": "nurse:x",
                     "sdp": {"type": "offer", "sdp": "v=0"}})
        m = b.receive_json()
        assert m["type"] == "rtc_offer" and m["from"] == "bed:E1" and m["to"] == "nurse:x"
        a.send_json({"type": "rtc_ice", "from": "bed:E1", "to": "nurse:x", "candidate": {"x": 1}})
        m = b.receive_json()
        assert m["type"] == "rtc_ice"


def test_non_whitelisted_frames_are_dropped(client):
    with client.websocket_connect("/ws/room/ROOMY") as a, \
         client.websocket_connect("/ws/room/ROOMY") as b:
        a.send_json({"type": "chat", "x": 1})                 # must NOT relay
        a.send_json({"type": "freeze_all", "payload": {}})    # also not a relay type
        a.send_json({"type": "intercom_text", "from": "nurse", "text": "hi"})  # relayed
        m = b.receive_json()
        # The first thing b sees is the intercom_text frame — the chat / freeze
        # frames were dropped, not forwarded ahead of it.
        assert m["type"] == "intercom_text" and m["text"] == "hi"


def test_room_isolation(client):
    # A frame sent to room RA must never reach a subscriber of room RB.
    with client.websocket_connect("/ws/room/RA") as a, \
         client.websocket_connect("/ws/room/RB") as b1, \
         client.websocket_connect("/ws/room/RB") as b2:
        a.send_json({"type": "intercom_text", "from": "nurse", "text": "FROM_A"})
        b1.send_json({"type": "intercom_text", "from": "nurse", "text": "FROM_B"})
        m = b2.receive_json()
        assert m["text"] == "FROM_B"              # RB only ever sees RB traffic


def test_malformed_json_is_ignored(client):
    with client.websocket_connect("/ws/room/ROOMZ") as a, \
         client.websocket_connect("/ws/room/ROOMZ") as b:
        a.send_text("not json {{{")               # ignored, connection stays open
        a.send_json({"type": "intercom_text", "from": "bed", "text": "ok"})
        m = b.receive_json()
        assert m["type"] == "intercom_text" and m["text"] == "ok"
