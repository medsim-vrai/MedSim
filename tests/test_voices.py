"""V4 — ElevenLabs voice service tests.

All tests run offline. Network-touching paths (live /v1/voices, /api/tts
to ElevenLabs) are exercised only for their *fallback* behavior — with no
key configured the service must degrade cleanly to the static catalog
and the browser-TTS fallback signal.
"""
from __future__ import annotations

import pytest

from portal import voices, library


# ──────────────────────────────────────────────────────────────────────
# Catalog + traits
# ──────────────────────────────────────────────────────────────────────

def test_fallback_catalog_loads_and_is_well_formed():
    cat = voices._fallback_catalog()
    assert len(cat) >= 20, "fallback catalog unexpectedly small"
    ids = set()
    for v in cat:
        assert v["voice_id"], "voice missing id"
        assert v["gender"] in ("male", "female", "neutral")
        assert v["age"] in ("young", "middle_aged", "old", "child")
        assert v["accent"], "voice missing accent"
        ids.add(v["voice_id"])
    assert len(ids) == len(cat), "duplicate voice_id in fallback catalog"


def test_persona_traits_cover_all_24_personas():
    for p in library.list_personas():
        t = voices.persona_traits(p["id"])
        assert t["sex"] in ("F", "M", "U"), f"{p['id']} bad sex {t['sex']}"
        assert t["age_band"] in ("child", "young", "middle_aged", "old")
        assert t["accent"], f"{p['id']} missing accent"
        assert t["ethnicity"], f"{p['id']} missing ethnicity"


def test_unknown_persona_gets_safe_default_traits():
    t = voices.persona_traits("P-NOPE")
    assert t["sex"] == "U"
    assert t["age_band"] == "middle_aged"


# ──────────────────────────────────────────────────────────────────────
# Candidate selection
# ──────────────────────────────────────────────────────────────────────

def test_candidates_returns_at_most_five():
    for pid in ("P-001", "P-013", "P-015", "P-023", "P-024"):
        out = voices.candidates_for(pid, api_key="")  # offline → fallback catalog
        assert len(out["candidates"]) <= 5, f"{pid} returned >5 candidates"
        assert out["candidates"], f"{pid} returned no candidates"


def test_candidates_respect_persona_sex():
    # P-001 Dr. Reyes is male → top candidate should be a male voice.
    out = voices.candidates_for("P-001", api_key="")
    top = out["candidates"][0]
    assert top["gender"] in ("male", "neutral"), \
        f"male persona got top voice gender={top['gender']}"

    # P-002 Dr. Patel is female → top candidate female.
    out = voices.candidates_for("P-002", api_key="")
    assert out["candidates"][0]["gender"] in ("female", "neutral")


def test_candidates_source_is_fallback_when_offline():
    out = voices.candidates_for("P-005", api_key="")
    assert out["source"] == "fallback"


def test_child_persona_prefers_youthful_voice():
    # P-015 Adi (age 7) → age band 'child'. The ranker maps child→young
    # and boosts childish descriptives; the top voice must not be 'old'.
    out = voices.candidates_for("P-015", api_key="")
    assert out["candidates"][0]["age"] != "old"


# ──────────────────────────────────────────────────────────────────────
# Key resolution
# ──────────────────────────────────────────────────────────────────────

def test_key_resolution_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "_runtime_key", "")  # isolate from the sticky cache
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-env-test")
    monkeypatch.setattr(voices, "KEYFILE", tmp_path / "nope.key")
    assert voices.get_api_key() == "sk-env-test"
    assert voices.is_configured() is True


def test_key_resolution_reads_keyfile(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "_runtime_key", "")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    kf = tmp_path / "elevenlabs.key"
    kf.write_text("sk-file-test\n")
    monkeypatch.setattr(voices, "KEYFILE", kf)
    assert voices.get_api_key() == "sk-file-test"


def test_key_resolution_empty_when_nothing_set(monkeypatch, tmp_path):
    monkeypatch.setattr(voices, "_runtime_key", "")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voices, "KEYFILE", tmp_path / "nope.key")
    assert voices.get_api_key() == ""
    assert voices.is_configured() is False


def test_health_reports_unconfigured_when_no_key():
    h = voices.health("")
    assert h["available"] is False
    assert h["source"] == "fallback"
    assert h["voice_count"] >= 20


# ──────────────────────────────────────────────────────────────────────
# Synthesis guard rails
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_stream_rejects_empty_inputs():
    for bad in [("", "v1", "k"), ("hello", "", "k"), ("hello", "v1", "")]:
        with pytest.raises(ValueError):
            agen = voices.synthesize_stream(*bad)
            await agen.__anext__()


# ──────────────────────────────────────────────────────────────────────
# HTTP routes (TestClient — offline; assert graceful fallback)
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    from portal import auth, credentials, control_session, voices as _voices
    # Ensure no stray keyfile / cached key leaks into the offline tests.
    # The sticky runtime cache (_runtime_key) is process-global, so an
    # earlier suite that resolved a real key would otherwise carry over.
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    control_session._active = None

    from portal import server
    if not credentials.is_initialized():
        credentials.initialize("test_passwd_xyz_8chars")
    vault = credentials.unlock("test_passwd_xyz_8chars")
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")

    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
    return c


def test_api_voices_returns_fallback_catalog_offline(client):
    r = client.get("/api/voices")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback"
    assert len(body["voices"]) >= 20


def test_api_voices_health_offline(client):
    r = client.get("/api/voices/health")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_api_voice_candidates_route(client):
    r = client.get("/api/voices/candidates/P-013")
    assert r.status_code == 200
    body = r.json()
    assert body["persona_id"] == "P-013"
    assert len(body["candidates"]) <= 5
    assert body["traits"]["sex"] == "F"


def test_api_tts_returns_fallback_signal_without_key(client):
    # No ElevenLabs key anywhere → /api/tts must 503 with {"fallback": true}
    # so the browser client degrades to SpeechSynthesis.
    r = client.get("/api/tts", params={"text": "hello", "voice_id": "21m00Tcm4TlvDq8ikWAM"})
    assert r.status_code == 503
    assert r.json()["fallback"] is True


def test_candidates_by_traits_route(client):
    # The legacy V1 voice session uses the query-param candidates route.
    r = client.get("/api/voices/candidates",
                    params={"sex": "M", "age_band": "old", "accent": "british"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["candidates"]) <= 5
    assert body["candidates"], "no candidates for M/old/british"
    # Top candidate should be male (hard signal).
    assert body["candidates"][0]["gender"] in ("male", "neutral")


def test_candidates_by_traits_function_defaults():
    # Missing keys must not raise — they fall back to safe defaults.
    out = voices.candidates_by_traits({}, api_key="")
    assert out["traits"]["sex"] == "U"
    assert out["traits"]["age_band"] == "middle_aged"
    assert len(out["candidates"]) <= 5


def test_runtime_key_cache_makes_key_sticky(monkeypatch, tmp_path):
    # After a vault resolution, a later keyless call still finds the key.
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voices, "KEYFILE", tmp_path / "none.key")
    monkeypatch.setattr(voices, "_runtime_key", "")

    class _FakeVault:
        def get(self, k):
            return "sk-cached-key" if k == "ELEVENLABS_API_KEY" else ""

    assert voices.get_api_key(_FakeVault()) == "sk-cached-key"
    # No vault, no env, no keyfile — the cache should still serve it.
    assert voices.get_api_key(None) == "sk-cached-key"


def test_voice_assignment_persists_on_session(client):
    # Start a session, then assign + read back a voice.
    client.post("/portal/control/start", data={
        "scenario_name": "voice test", "scenario_notes": "", "scenario_text": "",
        "program_id": "", "week": "", "modules": [], "personas": ["P-001"],
        "ehr_id": "helix",
    })
    r = client.post("/api/control/voice",
                    data={"persona_id": "P-001", "voice_id": "ErXwobaYiN019PkySvjV"})
    assert r.status_code == 200
    assert r.json()["voice_id"] == "ErXwobaYiN019PkySvjV"

    from portal import control_session
    assert control_session.get_active().voice_assignments["P-001"] == "ErXwobaYiN019PkySvjV"

    # Assigning "browser" clears it back to the fallback path.
    r = client.post("/api/control/voice",
                    data={"persona_id": "P-001", "voice_id": "browser"})
    assert r.status_code == 200
    assert "P-001" not in control_session.get_active().voice_assignments
