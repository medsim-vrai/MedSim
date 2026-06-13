"""FR-008 S5 — staged-error instructor API + builder page (auth'd routes)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portal import med_errors, med_orders

TEST_PASSWORD = "test_passwd_xyz_8chars"


def _ensure_vault():
    from portal import credentials
    vault_path = Path.home() / ".medsim" / "vault.enc"
    if vault_path.exists():
        try:
            credentials.unlock(TEST_PASSWORD)
            return
        except ValueError:
            vault_path.unlink()
    credentials.initialize(TEST_PASSWORD)


@pytest.fixture
def client(monkeypatch):
    """Logged-in instructor + a grounded active session (real med board, stubbed
    chart with MAR + documented allergy — the same grounding as the engine tests)."""
    _ensure_vault()
    from portal import control_session, ehr_db, server
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    sess = control_session.create_session(
        scenario_name="err-route-test",
        selected_personas=["P-001"], selected_modules=[], api_key="dummy")

    cond = next(k for k in med_orders.catalog() if not k.startswith("_"))
    med_orders.init_session(sess.id, cond)
    store = {"seed": {
        "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
        "medications": [
            {"name": "Heparin gtt", "dose": "see order", "route": "IV",
             "frequency": "cont", "status": "active"},
        ],
        "vitals_baseline": [{"time": "t-4h", "hr": "82", "rr": "16",
                             "spo2": "97", "bp": "118/74"}],
    }}
    monkeypatch.setattr(ehr_db, "seed",
                        lambda sid: copy.deepcopy(store["seed"]) if sid == sess.id else {})
    monkeypatch.setattr(ehr_db, "update_seed",
                        lambda sid, new: store.__setitem__("seed", copy.deepcopy(new)))
    monkeypatch.setattr(ehr_db, "orders", lambda sid: [])
    monkeypatch.setattr(ehr_db, "append_event",
                        lambda *a, **k: 1)
    c._sess = sess
    yield c
    med_orders._SESSION_MEDS.pop(sess.id, None)
    med_errors.clear_session(sess.id)
    control_session.end_active()


def test_routes_require_auth() -> None:
    _ensure_vault()
    from portal import server
    raw = TestClient(server.app)
    assert raw.get("/api/control/mederrors").status_code in (303, 401, 403)
    assert raw.get("/portal/control/errors").status_code in (303, 401, 403)


def test_taxonomy_and_state_endpoint(client) -> None:
    j = client.get("/api/control/mederrors").json()
    assert j["ok"] and j["errors"] == []
    tax = j["taxonomy"]
    trans = next(t for t in tax["types"] if t["id"] == "transcription")
    assert [v["id"] for v in trans["vectors"]] == ["verbal"]      # taxonomy filter
    admin = next(t for t in tax["types"] if t["id"] == "admin")
    assert [v["id"] for v in admin["vectors"]] == ["document"]
    assert "internal" not in str(tax).lower()                     # plain-English names


def test_full_wizard_flow_with_impact_and_lifecycle(client) -> None:
    sess = client._sess
    # Step 4 — grounded suggestions:
    j = client.get("/api/control/mederrors/suggest"
                   "?type=allergy&vector=verbal&encounter=med_pass").json()
    assert j["ok"] and j["candidates"], "documented Penicillin allergy must ground"
    cand = j["candidates"][0]
    # Step 5 — impact menu for that candidate:
    j = client.post("/api/control/mederrors/impacts",
                    json={"type": "allergy", "payload": cand}).json()
    assert j["ok"] and [p["profile"] for p in j["profiles"]] == ["anaphylaxis"]
    # Step 6 — arm with a moderate manual impact:
    j = client.post("/api/control/mederrors/arm", json={
        "type": "allergy", "vector": "verbal", "encounter": "med_pass",
        "payload": cand,
        "impact": {"profile": "anaphylaxis", "severity": "moderate",
                   "trigger": "manual"},
        "note": "route-test"}).json()
    assert j["ok"]
    eid = j["error_rec"]["id"]
    # Live card actions: trigger → stabilize → resolve(caught).
    assert client.post("/api/control/mederrors/trigger",
                       json={"error_id": eid}).json()["ok"]
    assert client.post("/api/control/mederrors/stabilize",
                       json={"error_id": eid}).json()["ok"]
    assert client.post("/api/control/mederrors/resolve",
                       json={"error_id": eid, "outcome": "caught",
                             "note": "spotted on read-back"}).json()["ok"]
    # Transcript carries the full arc for the debrief.
    lines = [e.text for e in sess.transcript
             if e.source_label == "⚠️ Staged error"]
    assert len(lines) == 4
    assert lines[0].startswith("ARMED") and "anaphylaxis/moderate" in lines[0]
    assert lines[1].startswith("IMPACT TRIGGERED")
    assert lines[2].startswith("STABILIZED")
    assert lines[3].startswith("RESOLVED e1 — CAUGHT")


def test_severe_manual_trigger_demands_confirmation_via_route(client) -> None:
    cand = client.get("/api/control/mederrors/suggest"
                      "?type=allergy&vector=verbal&encounter=report").json()["candidates"][0]
    eid = client.post("/api/control/mederrors/arm", json={
        "type": "allergy", "vector": "verbal", "encounter": "report",
        "payload": cand,
        "impact": {"profile": "anaphylaxis", "severity": "severe",
                   "trigger": "manual"}}).json()["error_rec"]["id"]
    bad = client.post("/api/control/mederrors/trigger", json={"error_id": eid})
    assert bad.status_code == 400 and "confirm" in bad.json()["error"]
    good = client.post("/api/control/mederrors/trigger",
                       json={"error_id": eid, "confirm_severe": True})
    assert good.json()["ok"]


def test_invalid_axes_and_unknown_ids_surface_cleanly(client) -> None:
    r = client.get("/api/control/mederrors/suggest"
                   "?type=transcription&vector=document&encounter=report")
    assert r.status_code == 400                                  # taxonomy enforced
    assert client.post("/api/control/mederrors/disarm",
                       json={"error_id": "e99"}).status_code == 404
    r = client.post("/api/control/mederrors/resolve",
                    json={"error_id": "e99", "outcome": "shrugged"})
    assert r.status_code == 400                                  # bad outcome named


def test_debrief_carries_the_staged_error_arc(client) -> None:
    """FR-008 S6 — the debrief artifact renders the full arc (what was planted,
    where, impact, outcome) with wall-clock timestamps."""
    from portal import debrief
    sess = client._sess
    cand = client.get("/api/control/mederrors/suggest"
                      "?type=interaction&vector=document&encounter=med_pass"
                      ).json()["candidates"][0]
    eid = client.post("/api/control/mederrors/arm", json={
        "type": "interaction", "vector": "document", "encounter": "med_pass",
        "payload": cand}).json()["error_rec"]["id"]
    client.post("/api/control/mederrors/resolve",
                json={"error_id": eid, "outcome": "missed", "note": "debrief anchor"})
    d = debrief.build(sess)
    arc = d["staged_errors"]
    assert len(arc) == 1
    e = arc[0]
    assert e["outcome"] == "missed" and e["note"] == "debrief anchor"
    assert e["type_display"] == "Dangerous interaction"
    assert e["armed_at"] and ":" in e["armed_at"]          # HH:MM
    assert e["delivered_at"]                               # document vector = immediate
    assert e["impact"] is None


def test_builder_page_renders_for_instructor(client) -> None:
    r = client.get("/portal/control/errors")
    assert r.status_code == 200
    assert "Staged error builder" in r.text
    assert "structured path" in r.text


# ── FR-008 S7 — per-encounter (multi-patient) staged errors ─────────────────────
import copy as _copy


@pytest.fixture
def room_client(monkeypatch):
    """Logged-in instructor + a TWO-bed room. Each bed is its own ControlSession
    with a grounded chart (MAR + documented allergy) so suggestions resolve."""
    _ensure_vault()
    from portal import control_room, control_session, ehr_db, med_orders, server
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})

    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    room = control_room.create_room(label="two-bed-test")
    cond = next(k for k in med_orders.catalog() if not k.startswith("_"))

    beds = {}
    for name in ("A", "B"):
        sess = control_session.ControlSession(
            id=f"bed-{name}", join_code=f"BED{name}1",
            scenario_name=f"Bed {name}", api_key="dummy",
            selected_personas=["P-001"], selected_modules=[], ehr_id="cyrus")
        room.add_encounter(sess)
        med_orders.init_session(sess.id, cond)
        beds[name] = sess

    seeds = {f"bed-{n}": {
        "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
        "medications": [{"name": "Heparin gtt", "dose": "see order", "route": "IV",
                         "frequency": "cont", "status": "active"}],
        "vitals_baseline": [{"time": "t-4h", "hr": "82", "bp": "118/74"}],
    } for n in ("A", "B")}
    monkeypatch.setattr(ehr_db, "seed", lambda sid: _copy.deepcopy(seeds.get(sid, {})))
    monkeypatch.setattr(ehr_db, "update_seed", lambda sid, new: seeds.__setitem__(sid, _copy.deepcopy(new)))
    monkeypatch.setattr(ehr_db, "orders", lambda sid: [])
    monkeypatch.setattr(ehr_db, "append_event", lambda *a, **k: 1)
    c._beds = beds
    yield c
    for n in ("A", "B"):
        med_orders._SESSION_MEDS.pop(f"bed-{n}", None)
        med_errors.clear_session(f"bed-{n}")
    control_room.end_active_room()


def test_multibed_requires_a_bed_selector(room_client):
    from portal import control_room
    # get_active() is None in a multi-bed room → no-bed call 409s.
    assert control_room.get_active() is None
    assert room_client.get("/api/control/mederrors").status_code == 409
    # An unknown bed is a clean 404.
    assert room_client.get("/api/control/mederrors?bed=nope").status_code == 404


def test_error_armed_on_one_bed_does_not_leak_to_the_other(room_client):
    # Both beds start empty.
    for n in ("A", "B"):
        j = room_client.get(f"/api/control/mederrors?bed=bed-{n}").json()
        assert j["ok"] and j["errors"] == []
    # Arm an error on bed A only.
    cand = room_client.get("/api/control/mederrors/suggest"
                           "?type=allergy&vector=verbal&encounter=med_pass&bed=bed-A"
                           ).json()["candidates"][0]
    armed = room_client.post("/api/control/mederrors/arm?bed=bed-A", json={
        "type": "allergy", "vector": "verbal", "encounter": "med_pass",
        "payload": cand}).json()
    assert armed["ok"]
    # Bed A shows it; bed B is still empty (per-bed isolation).
    a = room_client.get("/api/control/mederrors?bed=bed-A").json()["errors"]
    b = room_client.get("/api/control/mederrors?bed=bed-B").json()["errors"]
    assert len(a) == 1 and b == []
    # Lifecycle action also scopes by bed.
    eid = armed["error_rec"]["id"]
    assert room_client.post("/api/control/mederrors/resolve?bed=bed-A",
                            json={"error_id": eid, "outcome": "caught"}).json()["ok"]
    # Resolving on bed B for that id is a 404 (not present there).
    assert room_client.post("/api/control/mederrors/resolve?bed=bed-B",
                            json={"error_id": eid, "outcome": "caught"}).status_code == 404


def test_builder_page_scopes_to_a_bed(room_client):
    r = room_client.get("/portal/control/errors?bed=bed-A")
    assert r.status_code == 200
    assert "Bed: Bed A" in r.text
    assert '"bed-A"' in r.text or "bed-A" in r.text     # threaded into the page JS
