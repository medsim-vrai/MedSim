"""FR-019 N1 — NetworkSnapshot assembly (portal/network_status.build_snapshot).

Isolated via monkeypatch of the three deps (control_room / ehr_db / library) so we
exercise the mapping logic without launching a live room. Asserts the snapshot
matches the schema.ts contract shape + the device/role classification rules."""
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portal import network_status as ns

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
def client():
    _ensure_vault()
    from portal import server
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    return c


def _enc(eid, **kw):
    d = dict(id=eid, patient_persona_id=None, selected_personas=[],
             scenario_name="", encounter_label="", join_code="")
    d.update(kw)
    return types.SimpleNamespace(**d)


def _staff(sid, **kw):
    d = dict(display_name="", role="nurse", assignments=[], initials="")
    d.update(kw)
    return types.SimpleNamespace(staff_id=sid, **d)


def _room(encs, **kw):
    d = dict(room_id="room-1", label="Care room", shared_personas=[],
             cart_labels={}, staff={})
    d.update(kw)
    room = types.SimpleNamespace(encounters={e.id: e for e in encs}, **d)

    def _accessible(sid):
        # Mirrors control_room.accessible_encounter_ids: supervisory roles (and an
        # unassigned nurse) cover all beds; an assigned nurse covers its beds.
        sm = room.staff.get(sid)
        if sm is None:
            return []
        role = (getattr(sm, "role", "") or "").lower()
        assigns = [e for e in (getattr(sm, "assignments", []) or []) if e in room.encounters]
        if role in ("charge_nurse", "supervisor", "instructor") or not assigns:
            return list(room.encounters.keys())
        return assigns

    room.accessible_encounter_ids = _accessible
    return room


def test_empty_when_no_room(monkeypatch):
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: None)
    snap = ns.build_snapshot()
    assert snap["sessionId"] == ""
    assert snap["control"]["state"] == "fault"
    assert snap["commonDevices"] == []
    assert snap["units"] == []
    assert snap["students"] == []
    assert "timestamp" in snap


def test_patient_devices_and_roster(monkeypatch):
    enc = _enc("e1", patient_persona_id="ppid", selected_personas=["ppid", "doc1"],
               scenario_name="Chest pain")
    room = _room(
        [enc],
        shared_personas=["nurse1"],
        cart_labels={"cart-1": "Med cart A"},
        staff={"s1": _staff("s1", display_name="Pat", role="charge_nurse",
                            assignments=["e1"], initials="PT")},
    )
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: room)
    monkeypatch.setattr(ns._db, "device_stations", lambda eid: [
        {"id": "d1", "device_kind": "telemetry_monitor", "label": "Tele", "last_seen": time.time()},
        {"id": "d2", "device_kind": "pump_iv", "label": "IV", "last_seen": time.time() - 100},
    ] if eid == "e1" else [])
    monkeypatch.setattr(ns._db, "get_device_station", lambda cid: {"id": cid, "last_seen": time.time()})
    personas = {
        "ppid": {"name": "Mr X", "role": "patient"},
        "doc1": {"name": "Dr Who", "role": "doctor"},
        "nurse1": {"name": "RN", "role": "charge nurse"},
    }
    monkeypatch.setattr(ns._lib, "get_persona", lambda pid: personas.get(pid))

    snap = ns.build_snapshot()

    assert snap["sessionId"] == "room-1"
    assert snap["control"]["state"] == "active"

    room0 = snap["units"][0]["rooms"][0]
    assert room0["capacity"] == 8
    pat = room0["patients"][0]
    assert pat["tag"] == "PT-01" and pat["bed"] == 1
    # telemetry → manikin (physio), recent beat → active
    assert pat["manikin"]["cls"] == "physio" and pat["manikin"]["state"] == "active"
    # has a patient persona → a vrai tablet node
    assert pat["tablet"]["cls"] == "vrai"
    # pump → supporting, stale beat → fault
    assert len(pat["supporting"]) == 1
    assert pat["supporting"][0]["cls"] == "supporting"
    assert pat["supporting"][0]["state"] == "fault"

    # common devices: a med cart (operational) + character roles
    assert any(d["cls"] == "operational" for d in snap["commonDevices"])
    ops = {d["id"]: d for d in snap["commonDevices"] if d["cls"] == "operational"}
    assert ops["cart-1"]["state"] == "active"      # cart heartbeat fresh
    assert "records" in ops                         # medical-records surface always present
    assert "nursing" not in ops                     # single bed → no nurses station (matches Operate)
    chars = [d for d in snap["commonDevices"] if d["cls"] == "character"]
    roles = {d.get("role") for d in chars}
    assert "charge_nurse" in roles          # shared nurse1, role normalized
    assert "doctor" in roles                # per-bed doctor
    doc = [d for d in chars if d.get("role") == "doctor"][0]
    assert doc["assignedToPatientId"] == "e1"

    # students from the staff roster
    assert len(snap["students"]) == 1
    stu = snap["students"][0]
    assert stu["role"] == "charge_nurse"
    assert stu["patientIds"] == ["e1"]
    assert stu["name"] == "Pat"


def test_unknown_role_degrades_and_missing_parts(monkeypatch):
    enc = _enc("e1", patient_persona_id=None, selected_personas=["weird"])
    room = _room([enc], staff={})
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: room)
    monkeypatch.setattr(ns._db, "device_stations", lambda eid: [])
    monkeypatch.setattr(ns._lib, "get_persona", lambda pid: {"name": "W", "role": "janitor"})

    snap = ns.build_snapshot()
    chars = [d for d in snap["commonDevices"] if d["cls"] == "character"]
    assert chars and "role" not in chars[0]          # unknown role omitted, not crashed
    pat = snap["units"][0]["rooms"][0]["patients"][0]
    assert pat["tablet"] is None                      # no patient persona → no tablet
    assert pat["manikin"] is None                     # no devices
    assert pat["supporting"] == []


def test_shared_surfaces_records_and_nursing(monkeypatch):
    """Records (every room) + nurses station (multi-bed only) appear as shared
    operational devices, with state derived from live heartbeats/roster."""
    e1, e2 = _enc("e1"), _enc("e2")
    e1.ehr_stations = {"r1": types.SimpleNamespace(online=True)}      # a records station online
    room = _room([e1, e2], students={"st9": types.SimpleNamespace(role="nurse_station")})
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: room)
    monkeypatch.setattr(ns._db, "device_stations", lambda eid: [])
    monkeypatch.setattr(ns._db, "get_device_station", lambda cid: None)
    monkeypatch.setattr(ns._lib, "get_persona", lambda pid: None)

    snap = ns.build_snapshot()
    ops = {d["id"]: d for d in snap["commonDevices"] if d["cls"] == "operational"}
    assert ops["records"]["state"] == "active"        # an EHR station is online
    assert ops["nursing"]["state"] == "active"        # a nurse_station student is seated (multi-bed)


def test_supervisory_roles_cover_all_patients(monkeypatch):
    """Charge nurse / supervisor cover every bed (no explicit assignments needed);
    an assigned nurse covers only its bed."""
    e1, e2, e3 = _enc("e1"), _enc("e2"), _enc("e3")
    room = _room([e1, e2, e3], staff={
        "charge": _staff("charge", display_name="Chris", role="charge_nurse"),       # no assignments
        "sup": _staff("sup", display_name="Sam", role="supervisor"),                  # no assignments
        "rn": _staff("rn", display_name="Robin", role="nurse", assignments=["e2"]),   # one bed
    })
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: room)
    monkeypatch.setattr(ns._db, "device_stations", lambda eid: [])
    monkeypatch.setattr(ns._db, "get_device_station", lambda cid: None)
    monkeypatch.setattr(ns._lib, "get_persona", lambda pid: None)

    by_id = {s["id"]: s for s in ns.build_snapshot()["students"]}
    assert set(by_id["charge"]["patientIds"]) == {"e1", "e2", "e3"}    # covers all
    assert by_id["charge"]["role"] == "charge_nurse"
    assert set(by_id["sup"]["patientIds"]) == {"e1", "e2", "e3"}       # covers all
    assert by_id["sup"]["role"] == "supervising_nurse"
    assert by_id["rn"]["patientIds"] == ["e2"]                          # only its bed


# ── route wiring ───────────────────────────────────────────────────────────

def test_snapshot_route_requires_auth():
    from portal import server
    c = TestClient(server.app)
    assert c.get("/api/network/snapshot").status_code == 401
    assert c.get("/portal/network").status_code == 401


def test_snapshot_route_returns_valid_shape(client):
    r = client.get("/api/network/snapshot")
    assert r.status_code == 200
    snap = r.json()
    for key in ("sessionId", "timestamp", "control", "commonDevices", "units", "students"):
        assert key in snap
    assert snap["control"]["tag"] == "CTRL-01"
    assert isinstance(snap["commonDevices"], list)


def test_network_page_renders(client):
    html = client.get("/portal/network").text
    assert 'id="diagram"' in html                     # the SVG mount point
    assert "/static/network.js" in html               # the renderer
    assert "Tiered" in html and "Radial" in html      # both layout toggles
    assert "Device Link Topology" in html


# ── N0: roster ROLES fill the character tier (FR-019 decision 1) ─────────────

def _n0_room(monkeypatch, staff):
    enc = _enc("e1", patient_persona_id="ppid", selected_personas=["ppid", "doc1"])
    room = _room([enc], shared_personas=["rt1"], staff=staff)
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: room)
    monkeypatch.setattr(ns._db, "device_stations", lambda eid: [])
    monkeypatch.setattr(ns._db, "get_device_station", lambda cid: None)
    personas = {
        "ppid": {"name": "Mr X", "role": "patient"},
        "doc1": {"name": "Dr Who", "role": "doctor"},
        "rt1": {"name": "RT", "role": "respiratory therapist"},
    }
    monkeypatch.setattr(ns._lib, "get_persona", lambda pid: personas.get(pid))
    return room


def _char_node(snap, role):
    return next(n for n in snap["commonDevices"]
                if n.get("cls") == "character" and n.get("role") == role)


def test_student_in_role_fills_character_seat_active_when_seen(monkeypatch):
    staff = {"s1": _staff("s1", display_name="Sam", role="doctor",
                          initials="SM", last_seen=time.time())}
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    doc = _char_node(snap, "doctor")
    assert doc["studentId"] == "s1"
    assert doc["filledBy"] == "Sam"
    assert doc["state"] == "active"           # recently signed in → seat live
    # the unfilled RT seat stays an idle AI character
    rt = _char_node(snap, "respiratory_therapist")
    assert "studentId" not in rt and rt["state"] == "idle"


def test_rostered_but_absent_student_leaves_seat_idle(monkeypatch):
    staff = {"s1": _staff("s1", display_name="Sam", role="respiratory_therapist",
                          last_seen=None)}
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    rt = _char_node(snap, "respiratory_therapist")
    assert rt["studentId"] == "s1" and rt["state"] == "idle"


def test_two_students_same_role_fill_distinct_seats_once(monkeypatch):
    staff = {
        "s1": _staff("s1", display_name="A", role="doctor", last_seen=time.time()),
        "s2": _staff("s2", display_name="B", role="doctor", last_seen=time.time()),
    }
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    doc_nodes = [n for n in snap["commonDevices"]
                 if n.get("cls") == "character" and n.get("role") == "doctor"]
    assert len(doc_nodes) == 1                      # one doctor seat in this room
    assert doc_nodes[0]["studentId"] in ("s1", "s2")   # first fill wins, no clobber


def test_plain_nurse_role_fills_no_character_seat(monkeypatch):
    staff = {"s1": _staff("s1", display_name="N", role="nurse",
                          last_seen=time.time())}
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    assert all("studentId" not in n for n in snap["commonDevices"])


# ── N4: instructor-managed link state (FR-019 decision 2) ────────────────────

@pytest.fixture(autouse=True)
def _clear_overrides():
    ns._state_overrides.clear()
    yield
    ns._state_overrides.clear()


def test_override_paints_on_top_of_derived_state(monkeypatch):
    _n0_room(monkeypatch, {})
    assert ns.set_state_override("records", "fault") is True
    snap = ns.build_snapshot()
    rec = next(n for n in snap["commonDevices"] if n["id"] == "records")
    assert rec["state"] == "fault" and rec["managed"] is True
    # 'auto' clears → derived truth returns, no managed flag
    assert ns.set_state_override("records", "auto") is True
    snap = ns.build_snapshot()
    rec = next(n for n in snap["commonDevices"] if n["id"] == "records")
    assert rec["state"] in ("active", "idle") and "managed" not in rec


def test_override_rejects_bad_input():
    assert ns.set_state_override("", "fault") is False
    assert ns.set_state_override("x", "bogus") is False
    assert ns.set_state_override("x", "available") is True


def test_device_state_route_requires_instructor():
    from portal import server
    c = TestClient(server.app)
    r = c.post("/api/network/device_state", json={"id": "x", "state": "fault"})
    assert r.status_code == 401


def test_device_state_route_sets_and_validates(client):
    r = client.post("/api/network/device_state", json={"id": "records", "state": "available"})
    assert r.status_code == 200 and ns._state_overrides.get("records") == "available"
    r = client.post("/api/network/device_state", json={"id": "records", "state": "nah"})
    assert r.status_code == 400


# ── N0 review fixes: real register_staff seeds last_seen==created_at ──────────

def test_just_rostered_student_is_idle_not_active(monkeypatch):
    # register_staff seeds last_seen == created_at (== now); a never-signed-in
    # student must read IDLE, not active-for-30-min.
    now = time.time()
    staff = {"s1": _staff("s1", display_name="New", role="doctor",
                          last_seen=now, created_at=now)}
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    doc = _char_node(snap, "doctor")
    assert doc["studentId"] == "s1" and doc["state"] == "idle"


def test_genuinely_active_student_is_active(monkeypatch):
    now = time.time()
    staff = {"s1": _staff("s1", display_name="Live", role="doctor",
                          created_at=now - 120, last_seen=now - 5)}  # touched since join
    _n0_room(monkeypatch, staff)
    snap = ns.build_snapshot()
    assert _char_node(snap, "doctor")["state"] == "active"


def test_staff_roles_whitelist_admits_character_roles():
    # The whole N0 feature is dead if ehr_db clamps doctor/RT/pharmacist to nurse.
    from portal import ehr_db
    for r in ("doctor", "respiratory_therapist", "pharmacist"):
        assert r in ehr_db._STAFF_ROLES


def test_stale_override_self_prunes(monkeypatch):
    _n0_room(monkeypatch, {})
    assert ns.set_state_override("no_such_node", "fault") is True
    ns.build_snapshot()                       # a build with the node absent…
    assert "no_such_node" not in ns._state_overrides   # …drops the ghost override


def test_overrides_clear_when_session_ends(monkeypatch):
    ns.set_state_override("records", "fault")
    monkeypatch.setattr(ns._cr, "get_active_room", lambda: None)
    ns.build_snapshot()
    assert ns._state_overrides == {}
