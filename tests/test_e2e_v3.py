"""V3 — programmatic end-to-end test using FastAPI's TestClient.

Walks the same path a live operator + student would take, headlessly:

  1. Operator logs in
  2. Operator completes the wizard (scenario + module + persona + ehr_id)
  3. Operator hits Start
  4. Bootstrap exposes seeded patients via the configured EHR adapter
  5. Student joins the EHR (POST /ehr/join)
  6. Student emits chart events (note.save, vitals.record, order.place)
  7. Operator hits Charting complete (stub mode: no Haiku call)
  8. Operator opens the debrief — Documentation + Orders cards render

Designed to run in CI without network. The Haiku rubric call is bypassed
because `sess.api_key` is empty in test mode — `compare.rubric.evaluate`
returns a low-confidence default, which still exercises the persistence
+ debrief path. All EHR storage routes through `ehr_db`'s in-memory
mode (test session ids aren't real); the SQLite path is unaffected.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Spin a fresh TestClient with a throwaway vault directory.

    We monkeypatch the credentials module's vault path to keep the
    operator's real ~/.medsim/vault.enc untouched. The auth flow is
    bypassed by injecting a pre-built session cookie.
    """
    # Sandbox the vault dir BEFORE importing the portal module.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    from portal import auth, credentials, control_session, ehr_db, server

    # Reset the in-memory singletons so each test gets a clean slate.
    control_session._active = None
    ehr_db._mem.clear()
    ehr_db._mem_seeds.clear()
    ehr_db._mem_reports.clear()

    # Initialize a vault with a known password + dummy API key.
    if not credentials.is_initialized():
        credentials.initialize("test_passwd_xyz_8chars")
    vault = credentials.unlock("test_passwd_xyz_8chars")
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy-not-used-in-test")

    # Build a session cookie the same way the login flow does.
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    cookie = auth.issue_session_token(vault)
    c.cookies.set(auth.COOKIE_NAME, cookie)
    return c


def test_full_v3_flow(client):
    # ── 1. Operator starts a session via the wizard's POST endpoint ──
    r = client.post(
        "/portal/control/start",
        data={
            "scenario_name":  "E2E test scenario",
            "scenario_notes": "Headless flow exercising V3 lock-in path",
            "scenario_text":  "Postop day 1 cholecystectomy. 58yo woman, hx HTN, T2DM.",
            "program_id":     "BSN-RN",
            "week":           "8",
            "modules":        ["M22"],         # diabetes
            "personas":       ["P-013"],       # Mrs. Kowalski (geriatric pt)
            "ehr_id":         "helix",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"], body
    join_code = body["join_code"]
    assert len(join_code) == 6

    # ── 2. Student joins the EHR — register an ehr_station_id ───────
    r = client.post(
        "/ehr/join",
        data={"code": join_code, "device_label": "E2E test device"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    # /ehr/{join_code}/{station_id}
    parts = loc.split("/")
    station_id = parts[-1]
    assert station_id.startswith("ES-"), station_id

    # ── 3. Bootstrap returns the seeded chart for that ehr_id ───────
    r = client.get(f"/api/ehr/{join_code}/{station_id}/bootstrap")
    assert r.status_code == 200, r.text
    boot = r.json()
    assert boot["MODE"] == "live"
    assert boot["EHR_ID"] is None or boot.get("PATIENTS")  # adapter returned patients
    # The seed should carry the persona-derived MRN.
    seed = boot.get("SEED") or {}
    assert seed.get("mrn", "").startswith("HLX-"), seed.get("mrn")
    assert seed.get("safety_class") in ("baseline", "sensitive", "high-risk")
    # PATIENTS list from the helix adapter
    pts = boot.get("PATIENTS") or []
    assert len(pts) == 1
    pid = pts[0]["mrn"]

    # ── 4. Student emits a note, vitals, and a substantive comm log ──
    for ev in [
        {
            "type": "note.save", "surface": "notes", "patient_id": pid,
            "ehr_station_id": station_id, "ts_client": 1747400000000,
            "payload": {
                "note_id": "n1", "note_type": "Nursing Progress",
                "body": "Reviewed home metformin and discussed sick-day rules. "
                        "Patient denies hypoglycemia symptoms. SBAR handoff "
                        "given to night shift RN. No insulin held.",
                "signed": True, "template": "SBAR",
            },
        },
        {
            "type": "vitals.record", "surface": "vitals", "patient_id": pid,
            "ehr_station_id": station_id, "ts_client": 1747400001000,
            "payload": {"t": "37.0", "hr": "82", "rr": "16",
                         "bp": "128/76", "spo2": "97", "pain": "2"},
        },
        {
            "type": "communication.log", "surface": "comms", "patient_id": pid,
            "ehr_station_id": station_id, "ts_client": 1747400002000,
            "payload": {"addressee": "Provider",
                         "body": "Called Dr. Park re: persistently elevated glucose; verbal order received for sliding scale insulin."},
        },
    ]:
        r = client.post(f"/api/ehr/{join_code}/{station_id}/event", json=ev)
        assert r.status_code == 200, r.text
        assert r.json()["ok"]

    # ── 5. Student places an order (via /api/ehr/{join}/orders) ────
    r = client.post(
        f"/api/ehr/{join_code}/orders",
        json={
            "patient_id": pid, "ehr_station_id": station_id,
            "order": {
                "category": "lab", "code": "BMP", "label": "Basic metabolic panel",
                "rationale": "Repeat BMP given hyperglycemia and possible volume status change",
                "priority": "stat", "signed_by": "E2E test station",
            },
        },
    )
    assert r.status_code == 200, r.text

    # ── 6. The transcript needs >=1 student round-trip so the
    #       documentation_alignment card has something to compare against.
    #       We synthesize one directly on the ControlSession to avoid the
    #       full chat-station mock.
    from portal import control_session, library
    sess = control_session.get_active()
    assert sess is not None
    persona = library.get_persona("P-013")
    assert persona is not None
    sess.log_turn(
        source="station:fake_chat", source_label="E2E chat",
        persona_id=persona["id"], persona_name=persona["name"],
        student_text="Can you tell me about your metformin regimen and any hypoglycemia symptoms?",
        character_text="I take metformin twice a day with meals. No shakiness or sweating recently.",
        latency_ms=420,
    )
    sess.log_turn(
        source="station:fake_chat", source_label="E2E chat",
        persona_id=persona["id"], persona_name=persona["name"],
        student_text="Glucose has been elevated — I'm going to call the provider for a sliding-scale insulin order.",
        character_text="OK, whatever you think is best.",
        latency_ms=380,
    )

    # ── 7. Operator hits Charting complete — runs comparison (stub rubric) ──
    r = client.post("/portal/control/charting_complete")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"]
    assert 0.0 <= out["composite"] <= 1.0

    # Lock-in should freeze further writes.
    r = client.post(
        f"/api/ehr/{join_code}/{station_id}/event",
        json={"type": "note.save", "surface": "notes", "patient_id": pid,
              "ehr_station_id": station_id, "ts_client": 1747400999000,
              "payload": {"body": "post-lock edit"}},
    )
    assert r.status_code == 423, "should be locked after charting_complete"

    # ── 8. Debrief surfaces the two new V3 cards ────────────────────
    from portal import debrief as debrief_mod
    db = debrief_mod.build(sess)
    assert "documentation_alignment" in db
    assert "orders_alignment" in db
    da = db["documentation_alignment"]
    oa = db["orders_alignment"]
    assert da["available"] is True
    assert da["note_count"] >= 1, f"expected >=1 note, got {da}"
    assert da["signed_count"] >= 1
    assert isinstance(da["rules"]["hits"], list)
    assert isinstance(da["rules"]["misses"], list)
    assert oa["total_orders"] >= 1
    assert "lab" in oa["by_category"]
    # The metformin-rich note + transcript should produce at least one rules hit.
    hit_items = [h["item"].lower() for h in da["rules"]["hits"]]
    assert any("metformin" in i for i in hit_items), \
        f"expected metformin hit in documentation alignment; got {hit_items}"

    # Second charting_complete should 409 — already locked.
    r = client.post("/portal/control/charting_complete")
    assert r.status_code == 409


def test_demo_route_serves_each_ehr_bundle(client):
    # V5 — one functional engine served from _core/, themed per ehr_id.
    for ehr_id in ("helix", "cyrus", "meridian"):
        r = client.get(f"/ehr/demo/{ehr_id}")
        assert r.status_code == 200, f"demo failed for {ehr_id}: {r.text[:200]}"
        html = r.text
        assert "MEDSIM_V3" in html, "bootstrap global missing"
        assert "/ehr-static/_core/ehr_app.jsx" in html, "core engine not loaded"
        assert "/ehr-static/_core/themes.js" in html, "themes not loaded"
        assert '"MODE": "demo"' in html or '"MODE":"demo"' in html
        # The bootstrap pins which EHR theme the engine should use.
        assert f'"EHR_ID": "{ehr_id}"' in html or f'"EHR_ID":"{ehr_id}"' in html


def test_multi_station_chart_is_shared_and_lock_propagates(client):
    """V5 Phase 4 — the chart projection is session-scoped: a note written
    by one EHR station is visible to every other station's chart poll,
    and the operator's lock-in flips the shared `locked` flag."""
    client.post("/portal/control/start", data={
        "scenario_name": "multi-station", "scenario_notes": "", "scenario_text": "",
        "program_id": "", "week": "", "modules": ["M22"],
        "personas": ["P-013"], "ehr_id": "helix",
    })
    cs = client.get("/api/control/state").json()
    join = cs["join_code"]

    # Station 1 — launched on the control device.
    s1 = client.post("/portal/control/launch_ehr").json()["station_id"]
    # Station 2 — a student device joining via the EHR QR flow.
    r = client.post("/ehr/join", data={"code": join, "device_label": "Student tablet"},
                    follow_redirects=False)
    s2 = r.headers["location"].rsplit("/", 1)[-1]
    assert s1 != s2

    # Station 1 writes a note.
    client.post(f"/api/ehr/{join}/{s1}/event", json={
        "type": "note.save", "surface": "notes", "patient_id": "HLX-1",
        "ehr_station_id": s1, "ts_client": 1,
        "payload": {"note_id": "shared1", "note_type": "SBAR",
                    "body": "Station-1 note", "signed": True}})

    # Station 2's chart poll (same endpoint the UI polls) sees it.
    chart = client.get(f"/api/ehr/{join}/chart/HLX-1").json()
    assert any(n["body"] == "Station-1 note" for n in chart["notes"]), \
        "station 2 cannot see station 1's note — chart is not shared"
    assert chart["locked"] is False

    # Operator fires lock-in → the shared chart flips to locked.
    client.post("/portal/control/charting_complete")
    chart2 = client.get(f"/api/ehr/{join}/chart/HLX-1").json()
    assert chart2["locked"] is True, "lock-in did not propagate to the chart poll"


def test_ehr_state_endpoint_after_join(client):
    # Start session.
    client.post(
        "/portal/control/start",
        data={
            "scenario_name": "state test", "scenario_notes": "", "scenario_text": "",
            "program_id": "", "week": "",
            "modules": [], "personas": ["P-001"], "ehr_id": "cyrus",
        },
    )
    sess_resp = client.get("/api/ehr/state").json()
    assert sess_resp["active"] is True
    assert sess_resp["ehr_id"] == "cyrus"
    assert sess_resp["locked"] is False
    assert sess_resp["event_count"] == 0
    assert sess_resp["stations"] == []


def test_launch_ehr_on_this_device(client):
    """The control-panel 'Launch EHR on this device' button: registers a
    control-room EHR station and returns a URL the instructor opens in a
    new window. A repeat click must reuse the station, not pile up."""
    client.post(
        "/portal/control/start",
        data={
            "scenario_name": "launch test", "scenario_notes": "", "scenario_text": "",
            "program_id": "", "week": "",
            "modules": [], "personas": ["P-001"], "ehr_id": "helix",
        },
    )

    # First launch — mints a new control-room station.
    r = client.post("/portal/control/launch_ehr")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["reused"] is False
    assert j["ehr_id"] == "helix"
    station_id = j["station_id"]
    assert j["url"].endswith(station_id)
    assert "/ehr/" in j["url"]

    # The returned URL serves the full EHR bundle (Medical Records interface).
    r = client.get(j["url"])
    assert r.status_code == 200, r.text
    assert "MEDSIM_V3" in r.text or "MEDSIM V3" in r.text

    # The station shows up in the ops EHR roster, labelled for the operator.
    state = client.get("/api/ehr/state").json()
    labels = [s["device_label"] for s in state["stations"]]
    assert "Control room (instructor)" in labels

    # Second launch reuses the still-online station — no pile-up.
    r2 = client.post("/portal/control/launch_ehr")
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["reused"] is True
    assert j2["station_id"] == station_id
    state2 = client.get("/api/ehr/state").json()
    assert len(state2["stations"]) == 1

    # Ordering works from the launched station — place a lab order.
    cs = client.get("/api/control/state").json()
    r3 = client.post(
        f"/api/ehr/{cs['join_code']}/orders",
        json={"patient_id": "HLX-1", "ehr_station_id": station_id,
              "order": {"category": "lab", "code": "BMP",
                        "rationale": "baseline metabolic panel", "priority": "routine"}},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["ok"]

    # The button itself is a plain GET link — it must 303-redirect into a
    # working EHR bundle URL (no JS popup, no relative-URL pitfalls).
    r4 = client.get("/portal/control/launch_ehr", follow_redirects=False)
    assert r4.status_code == 303, r4.text
    loc = r4.headers["location"]
    assert loc.startswith("/ehr/"), loc
    # The redirect target reuses the same control-room station and serves
    # the full Medical Records interface.
    assert loc.endswith(station_id)
    r5 = client.get(loc)
    assert r5.status_code == 200, r5.text
    assert "MEDSIM_V3" in r5.text or "MEDSIM V3" in r5.text
    # V5 Phase 6 — the bootstrap carries the station's device label so
    # notes written here are attributed to the instructor.
    assert "Control room (instructor)" in r5.text


def test_master_catalog_extends_and_auto_promotes(client):
    """V5 Phase 6 — supplies/services/medications added at runtime join a
    persistent master catalog, and any ad-hoc order auto-joins it too, so
    they 'continue forward' as orderable items."""
    from portal import ehr_db
    client.post("/portal/control/start", data={
        "scenario_name": "catalog test", "scenario_notes": "", "scenario_text": "",
        "program_id": "", "week": "", "modules": [],
        "personas": ["P-013"], "ehr_id": "helix",
    })
    join = client.get("/api/control/state").json()["join_code"]
    s1 = client.post("/portal/control/launch_ehr").json()["station_id"]
    tag = str(int(time.time() * 1000))
    custom_code = f"WOUND VAC KIT {tag}"
    adhoc_code = f"INTERPRETER ASL {tag}"

    # Explicit add of a custom supply.
    r = client.post(f"/api/ehr/{join}/orders/catalog", json={
        "ehr_station_id": s1, "category": "supply",
        "code": custom_code, "label": "Negative-pressure wound therapy kit"})
    assert r.status_code == 200, r.text
    assert any(i["code"] == custom_code for i in r.json()["items"])

    # GET catalog reflects it, flagged as a custom addition.
    cat = client.get(f"/api/ehr/{join}/orders/catalog").json()
    hit = [i for i in cat["items"] if i["code"] == custom_code]
    assert hit and hit[0].get("added") is True

    # Auto-promotion: an order placed for a code not in the catalog
    # joins the master list automatically.
    client.post(f"/api/ehr/{join}/orders", json={
        "patient_id": "HLX-1", "ehr_station_id": s1,
        "order": {"category": "service", "code": adhoc_code,
                  "rationale": "patient is Deaf", "priority": "routine"}})
    cat2 = client.get(f"/api/ehr/{join}/orders/catalog").json()
    assert any(i["code"] == adhoc_code for i in cat2["items"]), \
        "ad-hoc order did not auto-join the master catalog"

    # The master list is global — visible from a different EHR too.
    other = ehr_db.catalog_additions("meridian")
    assert any(a["code"] == custom_code for a in other)

    # Clean up the global rows this test created.
    for a in ehr_db.catalog_additions(None):
        if a["code"] in (custom_code, adhoc_code):
            ehr_db.remove_catalog_item(a["id"])
