"""FR-011 G1 (ADR-0039) — portal resumability.

The educator's session config + med board + staged errors + handoff survive a
portal restart instead of being wiped. PHI (trainee free-text) is never in the
snapshot."""
from __future__ import annotations

import json

import pytest

from portal import control_session, handoff, med_errors, med_orders, session_state


@pytest.fixture
def isolated_store(monkeypatch):
    """Use ehr_db's in-memory fallback (no real DB writes) + a clean slate."""
    from portal import ehr_db
    monkeypatch.setattr(ehr_db, "_conn", lambda: None)
    ehr_db._mem_session_state = None
    yield
    ehr_db._mem_session_state = None
    if control_session.get_active() is not None:
        from portal import control_room
        control_room.end_active_room()
    med_orders._SESSION_MEDS.clear()
    med_errors._SESSION_ERRORS.clear()
    handoff._HANDOFFS.clear()


def _populate() -> str:
    """A configured session with med-board + a staged error + a handoff (incl.
    trainee survey text that must NOT be persisted)."""
    sess = control_session.create_session(
        scenario_name="ED · Mr. Hayes", selected_personas=["P-014", "P-040"],
        selected_modules=["M32"], api_key="secret-key", ehr_id="cyrus")
    sid = sess.id
    cond = next(k for k in med_orders.catalog() if not k.startswith("_"))
    med_orders.init_session(sid, cond)
    med_errors._SESSION_ERRORS[sid] = {"seq": 1, "errors": [{
        "id": "e1", "type": "wrong_dose", "vector": "document", "encounter": "charting",
        "payload": {"display": "Heparin 50000 units"}, "status": "delivered",
        "snapshot": {"key": "medications", "present": True, "value": []},
    }]}
    handoff._HANDOFFS[sid] = {
        "mode": "offgoing", "dial": "complete", "counterpart_id": "P-040",
        "persona_ids": ["P-014"], "order": ["P-014"], "packs": {"P-014": {"patient": {"name": "Hayes"}}},
        "phase": "survey", "cursor": 0, "started_at": 1.0,
        "said": {"P-014": {"meds", "identity"}},
        "survey": {"completeness": {"text": "TRAINEE PRIVATE ANSWER eight out of ten", "ts": 2.0}},
        "evaluation": {"P-014": {"coverage": {"meds": {"evidence": "TRAINEE QUOTE about heparin"}}}},
    }
    return sid


def test_snapshot_round_trips_every_module(isolated_store):
    sid = _populate()
    blob = session_state.snapshot()
    assert blob and blob["version"] == session_state.VERSION
    # control session config captured (id preserved, no api key).
    enc = blob["control_session"]["encounters"][0]
    assert enc["id"] == sid and enc["scenario_name"] == "ED · Mr. Hayes"
    assert enc["selected_personas"] == ["P-014", "P-040"]
    assert "api_key" not in enc and "secret-key" not in json.dumps(blob)
    # med board + staged error captured.
    assert sid in blob["med_orders"] and blob["med_errors"][sid]["errors"][0]["id"] == "e1"
    # handoff config captured; said-set serialized as a list.
    assert sorted(blob["handoff"][sid]["said"]["P-014"]) == ["identity", "meds"]


def test_snapshot_excludes_trainee_free_text(isolated_store):
    _populate()
    raw = json.dumps(session_state.snapshot())
    assert "TRAINEE PRIVATE ANSWER" not in raw   # survey answer excluded (PHI)
    assert "TRAINEE QUOTE" not in raw            # evaluation evidence excluded (PHI)


def test_simulated_restart_resumes_everything(isolated_store):
    sid = _populate()
    assert session_state.persist() is True
    # Simulate a restart: wipe ALL in-memory state.
    from portal import control_room
    control_room.end_active_room()
    med_orders._SESSION_MEDS.clear()
    med_errors._SESSION_ERRORS.clear()
    handoff._HANDOFFS.clear()
    assert control_session.get_active() is None
    # Resume.
    summary = session_state.resume()
    assert summary and summary["n_encounters"] == 1
    restored = control_session.get_active()
    assert restored is not None and restored.id == sid           # SAME id
    assert restored.scenario_name == "ED · Mr. Hayes"
    assert restored.api_key == ""                                # key re-acquired later
    # Keyed module state lines up with the restored id.
    assert med_orders.get_state(sid) is not None
    assert med_errors.state(sid)["errors"][0]["id"] == "e1"
    h = handoff.get(sid)
    assert h["mode"] == "offgoing" and h["counterpart_id"] == "P-040"
    assert h["said"]["P-014"] == {"identity", "meds"}            # list → set restored
    assert h["survey"] == {} and h["evaluation"] == {}           # PHI not restored


def test_nothing_to_save_with_no_active_session(isolated_store):
    assert session_state.snapshot() is None
    assert session_state.persist() is False


def test_resume_is_none_without_a_snapshot(isolated_store):
    assert session_state.resume() is None


def test_version_mismatch_and_corrupt_blob_are_safe(isolated_store, monkeypatch):
    from portal import ehr_db
    # Future/incompatible version → no restore (clean start), never raises.
    ehr_db.save_session_state(json.dumps({"version": 999, "control_session": {}}))
    assert session_state.resume() is None
    # Corrupt JSON → load_latest tolerates it.
    ehr_db._mem_session_state = "{not json"
    assert session_state.load_latest() is None
    assert session_state.resume() is None
