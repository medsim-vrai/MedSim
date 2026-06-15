"""FR-011 G2 — readiness / health as a service.

readiness.snapshot() is the ONE call the mission-control GUI polls to paint its
readiness bar + Setup board: per-subsystem green/amber/red with a detail line
and any one-tap actions. These tests pin the contract (shape + every check id +
status vocabulary), the colour logic of each individual check, and the only
executable action (resume the last session)."""
from __future__ import annotations

from pathlib import Path

import pytest

from portal import control_session, readiness, session_state

_VALID = {readiness.GREEN, readiness.AMBER, readiness.RED}
_EXPECTED_IDS = {"portal", "network", "cert", "voice", "speech",
                 "storage", "ehr", "vault", "session", "devices"}


@pytest.fixture
def isolated_store(monkeypatch):
    """ehr_db in-memory fallback + a clean control session slate (mirrors the
    session_state tests so readiness sees a deterministic world)."""
    from portal import ehr_db
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    yield
    ehr_db._mem_session_state = None
    if control_session.get_active() is not None:
        from portal import control_room
        control_room.end_active_room()


# ── contract ─────────────────────────────────────────────────────────────────

def test_snapshot_shape_and_every_check_present():
    """Runs the REAL checks (read-only) — validates end-to-end wiring + that the
    GUI always gets all seven subsystems with a valid status + actions list."""
    snap = readiness.snapshot()
    assert snap["overall"] in _VALID
    ids = {c["id"] for c in snap["checks"]}
    assert ids == _EXPECTED_IDS
    for c in snap["checks"]:
        assert c["status"] in _VALID
        assert c["label"] and isinstance(c["detail"], str)
        assert isinstance(c["actions"], list)
        for a in c["actions"]:
            assert a["id"] and a["label"]


def test_overall_rolls_up_worst_status(monkeypatch):
    def fake(status):
        return lambda vault=None: readiness._check("x", "X", status, "")
    monkeypatch.setattr(readiness, "_CHECKS", (fake(readiness.GREEN), fake(readiness.GREEN)))
    assert readiness.snapshot()["overall"] == readiness.GREEN
    monkeypatch.setattr(readiness, "_CHECKS", (fake(readiness.GREEN), fake(readiness.AMBER)))
    assert readiness.snapshot()["overall"] == readiness.AMBER
    monkeypatch.setattr(readiness, "_CHECKS", (fake(readiness.AMBER), fake(readiness.RED)))
    assert readiness.snapshot()["overall"] == readiness.RED


def test_one_broken_check_never_breaks_the_bar(monkeypatch):
    def boom(vault=None):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(readiness, "_CHECKS", (readiness._portal, boom))
    snap = readiness.snapshot()
    assert [c["id"] for c in snap["checks"]] == ["portal"]   # bad one dropped, no raise


# ── individual checks ────────────────────────────────────────────────────────

def test_portal_is_green():
    assert readiness._portal()["status"] == readiness.GREEN


def test_network_loopback_is_amber_external_is_green(monkeypatch):
    monkeypatch.setenv("MEDSIM_HOST", "127.0.0.1")
    assert readiness._network()["status"] == readiness.AMBER
    monkeypatch.setenv("MEDSIM_HOST", "0.0.0.0")
    monkeypatch.setattr(readiness, "_lan_ip", lambda: "192.168.1.50")
    assert readiness._network()["status"] == readiness.GREEN


def test_cert_missing_is_red(monkeypatch):
    monkeypatch.setattr(readiness, "_CERT_PATH", Path("/no/such/cert.pem"))
    assert readiness._cert()["status"] == readiness.RED


def test_cert_san_coverage_drives_amber_vs_green(monkeypatch, tmp_path):
    fake = tmp_path / "dev-cert.pem"
    fake.write_bytes(b"-- not parsed, file just has to exist --")
    monkeypatch.setattr(readiness, "_CERT_PATH", fake)
    monkeypatch.setattr(readiness, "_cert_sans", lambda: ["127.0.0.1", "192.168.1.50"])
    monkeypatch.setattr(readiness, "_lan_ip", lambda: "192.168.1.99")  # not covered
    out = readiness._cert()
    assert out["status"] == readiness.AMBER and "192.168.1.99" in out["detail"]
    monkeypatch.setattr(readiness, "_lan_ip", lambda: "192.168.1.50")  # covered
    assert readiness._cert()["status"] == readiness.GREEN


def test_voice_needs_anthropic_key(monkeypatch):
    from types import SimpleNamespace
    # No vault → can't verify → amber (log in).
    assert readiness._voice(None)["status"] == readiness.AMBER
    # Vault without the Anthropic key → RED (characters can't reply).
    out = readiness._voice(SimpleNamespace(credentials={}))
    assert out["status"] == readiness.RED and "Anthropic" in out["detail"]
    # Anthropic set, no ElevenLabs → green, notes the browser-TTS fallback.
    out = readiness._voice(SimpleNamespace(credentials={"ANTHROPIC_API_KEY": "sk-x"}))
    assert out["status"] == readiness.GREEN and "browser TTS" in out["detail"]
    # Both set → green.
    out = readiness._voice(SimpleNamespace(
        credentials={"ANTHROPIC_API_KEY": "sk-x", "ELEVENLABS_API_KEY": "el-y"}))
    assert out["status"] == readiness.GREEN and "ElevenLabs" in out["detail"]


def test_speech_warm_vs_cold(monkeypatch):
    from portal import room_stt
    monkeypatch.setattr(room_stt, "_engine", object(), raising=False)
    assert readiness._speech()["status"] == readiness.GREEN
    monkeypatch.setattr(room_stt, "_engine", None, raising=False)
    monkeypatch.setattr(room_stt, "_engine_err", None, raising=False)
    out = readiness._speech()
    assert out["status"] == readiness.AMBER
    assert any(a["id"] == "warm_speech" for a in out["actions"])   # cold → offers Warm
    monkeypatch.setattr(room_stt, "_engine_err", "OOM loading model", raising=False)
    out = readiness._speech()
    assert out["status"] == readiness.AMBER and "OOM" in out["detail"]


def test_ehr_selection(isolated_store):
    assert readiness._ehr()["status"] == readiness.AMBER          # no active session
    control_session.create_session(
        scenario_name="ED", selected_personas=["P-014"], selected_modules=[],
        api_key="k", ehr_id="cyrus")
    out = readiness._ehr()
    assert out["status"] == readiness.GREEN and "cyrus" in out["detail"]


def test_ehr_unselected_is_amber(isolated_store):
    control_session.create_session(
        scenario_name="ED", selected_personas=["P-014"], selected_modules=[],
        api_key="k", ehr_id="")
    assert readiness._ehr()["status"] == readiness.AMBER


def test_storage_durable_green_degraded_red(monkeypatch):
    from portal import ehr_db
    monkeypatch.setattr(ehr_db, "storage_status",
                        lambda: {"durable": True, "schema_version": 7})
    assert readiness._storage()["status"] == readiness.GREEN
    monkeypatch.setattr(ehr_db, "storage_status",
                        lambda: {"durable": False, "degraded_reason": "disk full"})
    out = readiness._storage()
    assert out["status"] == readiness.RED and "disk full" in out["detail"]


def test_session_offers_resume_when_a_snapshot_exists(isolated_store):
    sess = control_session.create_session(
        scenario_name="ED · Mr. Hayes", selected_personas=["P-014"],
        selected_modules=[], api_key="k", ehr_id="cyrus")
    assert session_state.persist() is True
    from portal import control_room
    control_room.end_active_room()
    assert control_session.get_active() is None
    out = readiness._session()
    assert out["status"] == readiness.AMBER
    assert any(a["id"] == "resume_session" for a in out["actions"])
    assert sess.scenario_name in out["detail"]


def test_session_active_is_green(isolated_store):
    control_session.create_session(
        scenario_name="ED · Live", selected_personas=["P-014"],
        selected_modules=[], api_key="k", ehr_id="cyrus")
    out = readiness._session()
    assert out["status"] == readiness.GREEN and not out["actions"]


# ── actions ──────────────────────────────────────────────────────────────────

def test_resume_action_restores_the_session(isolated_store):
    sess = control_session.create_session(
        scenario_name="ED · Resume me", selected_personas=["P-014"],
        selected_modules=[], api_key="k", ehr_id="cyrus")
    sid = sess.id
    assert session_state.persist() is True
    from portal import control_room
    control_room.end_active_room()
    assert control_session.get_active() is None
    result = readiness.run_action("resume_session")
    assert result["ok"] is True
    restored = control_session.get_active()
    assert restored is not None and restored.id == sid


def test_warm_speech_action_warms_without_blocking(monkeypatch):
    from portal import room_stt
    called = {"n": 0}
    monkeypatch.setattr(room_stt, "warm_in_background", lambda: called.__setitem__("n", 1))
    out = readiness.run_action("warm_speech")
    assert out["ok"] is True and called["n"] == 1


def test_restart_hint_is_info_only_never_restarts():
    out = readiness.run_action("restart_hint")
    assert out["ok"] is True
    assert "run_portal.py" in out["hint"]          # returns the command, doesn't run it


def test_recheck_cert_and_test_all_are_safe(monkeypatch):
    from portal import room_stt
    monkeypatch.setattr(room_stt, "_engine", object(), raising=False)  # already warm
    assert readiness.run_action("recheck_cert")["ok"] is True
    assert readiness.run_action("test_all")["ok"] is True


def test_unknown_action_is_rejected():
    out = readiness.run_action("delete_everything")
    assert out["ok"] is False and "delete_everything" in out["error"]
