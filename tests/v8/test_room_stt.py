"""ADR-0038 — room-local STT: POST /api/face/stt (the Mac transcribes for the
audio-only stations). The whisper engine is STUBBED — these tests cover the
route contract (payload validation, token posture, error surfaces), not the
model. The buffer must never be persisted; the route returns text only."""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

from portal import room_stt


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeEngine:
    """Stands in for faster_whisper.WhisperModel (loaded lazily in room_stt)."""

    def __init__(self, texts):
        self._texts = texts
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        self.last_samples = len(audio)
        self.last_audio = audio
        self.last_kwargs = kwargs
        return [_FakeSegment(t) for t in self._texts], None


def _pcm(seconds: float) -> bytes:
    n = int(seconds * room_stt.SAMPLE_RATE)
    return struct.pack(f"<{n}f", *([0.01] * n))


@pytest.fixture
def client(monkeypatch):
    from portal import server
    # Stub at the LOADER, not the engine slot: the slot is a module global the
    # (production) warm thread also writes, which once clobbered a stub mid-test.
    fake = _FakeEngine([" Send the ", "ampicillin. "])
    monkeypatch.setattr(room_stt, "_load_engine", lambda: fake)
    monkeypatch.delenv("MEDSIM_FACE_TOKEN", raising=False)
    c = TestClient(server.app)
    c.fake_engine = fake
    return c


def test_transcribes_pcm_to_joined_trimmed_text(client) -> None:
    r = client.post("/api/face/stt", content=_pcm(1.0))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["text"] == "Send the ampicillin."
    assert body["model"] == room_stt.model_name()
    assert isinstance(body["ms"], int)
    # The engine saw the samples we sent PLUS the FR-021 trailing-silence pad
    # (whisper drops a final word ending exactly at the PTT-release clip edge).
    pad = int(room_stt.SAMPLE_RATE * 0.45)
    assert client.fake_engine.last_samples == room_stt.SAMPLE_RATE + pad
    assert all(s == 0.0 for s in client.fake_engine.last_audio[-pad:])   # pad IS silence
    assert client.fake_engine.last_audio[0] != 0.0                       # speech untouched


def test_rejects_too_short_and_misaligned_bodies(client) -> None:
    assert client.post("/api/face/stt", content=_pcm(0.1)).status_code == 400
    assert client.post("/api/face/stt", content=_pcm(1.0) + b"x").status_code == 400


def test_rejects_clips_over_30s(client) -> None:
    over = bytes(room_stt._MAX_BYTES + 4)
    assert client.post("/api/face/stt", content=over).status_code == 413


def test_engine_failure_is_503_not_crash(client, monkeypatch) -> None:
    monkeypatch.setattr(room_stt, "_load_engine", lambda: None)
    monkeypatch.setattr(room_stt, "_engine_err", "boom")
    r = client.post("/api/face/stt", content=_pcm(1.0))
    assert r.status_code == 503
    assert "unavailable" in r.json()["error"]


def test_session_drug_names_reach_the_engine_as_hotwords(client, monkeypatch) -> None:
    """ADR-0038 accuracy lever: with an active session, the med board's drug
    names ride along as recognizer hints (A/B-proven: 'seftriaxone' →
    'ceftriaxone'). Without a session, no hints."""
    monkeypatch.setattr(room_stt, "session_vocab", lambda: "Ampicillin, Ceftriaxone")
    assert client.post("/api/face/stt", content=_pcm(1.0)).status_code == 200
    assert client.fake_engine.last_kwargs["hotwords"] == "Ampicillin, Ceftriaxone"

    monkeypatch.setattr(room_stt, "session_vocab", lambda: None)
    assert client.post("/api/face/stt", content=_pcm(1.0)).status_code == 200
    assert client.fake_engine.last_kwargs["hotwords"] is None


def test_session_vocab_collects_board_and_mar_names(monkeypatch) -> None:
    from portal import control_session, med_orders

    class _Sess:
        id = "s-vocab-test"

    monkeypatch.setattr(control_session, "get_active", lambda: _Sess())
    monkeypatch.setattr(med_orders, "active_med_names",
                        lambda sid: ["Acetaminophen", "ampicillin"])  # dup, case-insensitive
    condition = next(k for k in med_orders.catalog() if not k.startswith("_"))
    med_orders.init_session("s-vocab-test", condition)
    try:
        vocab = room_stt.session_vocab()
        assert vocab is not None
        board_drugs = [it["drug"] for it in med_orders.get_state("s-vocab-test")["items"]]
        assert board_drugs[0] in vocab          # the board is represented
        assert "Acetaminophen" in vocab         # the MAR is represented
        assert vocab.lower().count("ampicillin") <= 1  # dedupe holds either way
        # Doses/availability must NOT leak into the recognizer hints.
        assert "mg" not in vocab.lower()
    finally:
        med_orders._SESSION_MEDS.pop("s-vocab-test", None)


def test_session_vocab_is_none_without_a_session(monkeypatch) -> None:
    from portal import control_session
    monkeypatch.setattr(control_session, "get_active", lambda: None)
    assert room_stt.session_vocab() is None


def test_onboard_page_serves_over_https_route(client) -> None:
    """Runbook §3b: Android HTTPS-First can't reach the :8766 helper — the same
    instructions must exist ON the portal origin. No auth; links the CA."""
    r = client.get("/onboard")
    assert r.status_code == 200
    assert "/rootca.pem" in r.text
    assert "CA certificate" in r.text


def test_device_token_enforced_when_enabled(client, monkeypatch) -> None:
    """Same ADR-0027 posture as /listen: open by default, HMAC when opted in."""
    from portal import vrai_faces
    monkeypatch.setenv("MEDSIM_FACE_TOKEN", "1")
    bad = client.post("/api/face/stt?scenario=s1&character=P-006&token=nope",
                      content=_pcm(1.0))
    assert bad.status_code == 403
    good_token = vrai_faces.face_token("s1", "P-006")
    good = client.post(
        f"/api/face/stt?scenario=s1&character=P-006&token={good_token}",
        content=_pcm(1.0))
    assert good.status_code == 200
    assert good.json()["ok"] is True
