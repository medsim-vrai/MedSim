"""V5 — ehr_db persistence + fold tests.

Covers: round-trip event store/retrieve, fold projection (notes
latest-write-wins, orders, meds, results, vitals), comparison report
storage, schema-version migrations, and — critically — that chart
content survives a simulated server restart (connection close/reopen).
"""
from __future__ import annotations

import time

from portal import ehr_db


def _fresh(session_id: str = "test_session_xyz") -> str:
    """Clear any prior state for this test session id."""
    ehr_db.purge_session(session_id)
    return session_id


def test_event_round_trip():
    sid = _fresh("test_event_round_trip")
    eid = ehr_db.append_event(sid, "ES-a",
                              type="vitals.record", surface="vitals",
                              payload={"t": "37.0", "hr": "92"})
    assert eid >= 0
    events = ehr_db.events(sid)
    assert len(events) == 1
    assert events[0]["type"] == "vitals.record"
    assert events[0]["payload"]["hr"] == "92"
    ehr_db.purge_session(sid)


def test_fold_latest_note_wins():
    sid = _fresh("test_fold_latest_note_wins")
    ehr_db.append_event(sid, "ES-a", type="note.save", surface="notes",
                         payload={"note_id": "n1", "body": "v1", "signed": False})
    ehr_db.append_event(sid, "ES-a", type="note.save", surface="notes",
                         payload={"note_id": "n1", "body": "v2 final", "signed": True})
    proj = ehr_db.fold(sid)
    notes = proj["notes"]
    assert len(notes) == 1
    assert notes[0]["body"] == "v2 final"
    assert notes[0]["signed"] is True
    ehr_db.purge_session(sid)


def test_orders_are_captured():
    sid = _fresh("test_orders_are_captured")
    ehr_db.append_order(sid, "ES-a", patient_id="HLX-001",
                        order={"category": "lab", "code": "BMP", "rationale": "acute change"})
    o = ehr_db.orders(sid)
    assert len(o) == 1
    assert o[0]["order"]["code"] == "BMP"
    # The order should also appear as a chart_event of type order.place.
    evs = [e for e in ehr_db.events(sid) if e["type"] == "order.place"]
    assert len(evs) == 1
    ehr_db.purge_session(sid)


def test_save_and_get_comparison():
    sid = _fresh("test_comparison_report")
    rules = {"hits": [{"item": "x"}], "misses": [], "speculative": [],
             "totals": {"hits": 1, "misses": 0, "rules_score": 1.0}}
    rubric = {"completeness": 3, "accuracy": 3, "sbar_quality": 3,
              "prioritization": 3, "safety": 3, "narrative_feedback": "good"}
    ehr_db.save_comparison(sid, rules, rubric, score=0.85, model="claude-haiku-4-5")
    r = ehr_db.get_comparison(sid)
    assert r is not None
    assert r["score"] == 0.85
    assert r["model"] == "claude-haiku-4-5"
    assert r["rubric"]["completeness"] == 3
    ehr_db.purge_session(sid)


# ── V5 — hardening tests ───────────────────────────────────────────────

def test_fold_projects_orders_meds_and_results():
    """fold() now covers the full §10 event catalog, not just notes/vitals."""
    sid = _fresh("test_fold_full_catalog")
    ehr_db.append_order(sid, "ES-a", patient_id="P1",
                        order={"category": "med", "code": "Ceftriaxone 1g IV"})
    ehr_db.append_event(sid, "ES-a", type="med.administer", surface="mar",
                        payload={"med": "Ceftriaxone 1g IV", "route": "IV"})
    ehr_db.append_event(sid, "ES-a", type="result.acknowledge", surface="results",
                        payload={"result_id": "lab-7", "name": "Lactate"})
    ehr_db.append_event(sid, "ES-a", type="output.record", surface="io",
                        payload={"kind": "urine", "ml": 250})
    proj = ehr_db.fold(sid)
    assert len(proj["orders"]) == 1
    assert proj["orders"][0]["order"]["code"] == "Ceftriaxone 1g IV"
    assert proj["orders"][0]["order"]["order_id"]          # stamped automatically
    assert len(proj["meds_administered"]) == 1
    assert len(proj["results_acknowledged"]) == 1
    assert proj["results_acknowledged"][0]["result_id"] == "lab-7"
    assert len(proj["output"]) == 1
    ehr_db.purge_session(sid)


def test_order_modify_updates_status():
    sid = _fresh("test_order_modify")
    ehr_db.append_order(sid, "ES-a", patient_id="P1",
                        order={"category": "lab", "code": "BMP"})
    oid = ehr_db.fold(sid)["orders"][0]["order_id"]
    ehr_db.append_event(sid, "ES-a", type="order.modify", surface="orders",
                        payload={"order_id": oid, "action": "discontinue"})
    folded = ehr_db.fold(sid)["orders"][0]
    assert folded["status"] == "discontinued"
    assert len(folded["modifications"]) == 1
    ehr_db.purge_session(sid)


def test_schema_version_is_recorded():
    """The migration runner must stamp schema_version so an older ehr.db
    upgrades cleanly instead of silently missing tables."""
    conn = ehr_db._conn()
    if conn is None:
        import pytest
        pytest.skip("SQLite unavailable in this environment")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    assert row[0] == ehr_db.SCHEMA_VERSION


def test_storage_status_reports_durable_mode():
    st = ehr_db.storage_status()
    assert st["mode"] in ("sqlite", "memory")
    assert "db_path" in st and "schema_version" in st
    if st["mode"] == "sqlite":
        assert st["durable"] is True
        assert st["degraded_reason"] is None


def test_master_catalog_add_persists_across_restart():
    """V5 Phase 6 — a custom catalog item is global + persistent: it
    survives a connection cycle (i.e. a server restart) and is visible to
    every EHR."""
    if ehr_db._conn() is None:
        import pytest
        pytest.skip("SQLite unavailable")
    code = f"TEST-WOUNDVAC-{int(time.time() * 1000)}"
    ehr_db.add_catalog_item("supply", code, "Test wound-vac kit", added_by="pytest")

    # Simulate a restart.
    if ehr_db._shared is not None:
        ehr_db._shared.close()
    ehr_db._shared = None
    ehr_db._db_ready = False
    ehr_db._mem_catalog.clear()

    # Visible to any EHR (global scope) and still present after the restart.
    for ehr_id in ("helix", "cyrus", "meridian"):
        adds = ehr_db.catalog_additions(ehr_id)
        match = [a for a in adds if a["code"] == code]
        assert len(match) == 1, f"custom item missing for {ehr_id}"
        assert match[0]["category"] == "supply"
    # Clean up so the global catalog doesn't accumulate test rows.
    ehr_db.remove_catalog_item(match[0]["id"])
    assert all(a["code"] != code for a in ehr_db.catalog_additions(None))


def test_fold_note_carries_author():
    sid = _fresh("test_note_author")
    ehr_db.append_event(sid, "ES-a", type="note.save", surface="notes",
                        payload={"note_id": "n1", "body": "x", "signed": True,
                                 "author": "Control room (instructor)"})
    note = ehr_db.fold(sid)["notes"][0]
    assert note["author"] == "Control room (instructor)"
    ehr_db.purge_session(sid)


def test_content_survives_simulated_server_restart():
    """The core durability guarantee: write chart content, drop the DB
    connection (as a process restart would), reconnect, and confirm the
    notes/orders/events are all still there."""
    if ehr_db._conn() is None:
        import pytest
        pytest.skip("SQLite unavailable — durability not testable")

    sid = _fresh("test_restart_durability")
    ehr_db.register_session(sid, "JOIN01", "helix", "P-013", {"mrn": "HLX-1"})
    ehr_db.append_event(sid, "ES-a", type="note.save", surface="notes",
                        payload={"note_id": "n1", "body": "Pre-restart note",
                                 "signed": True})
    ehr_db.append_order(sid, "ES-a", patient_id="HLX-1",
                        order={"category": "lab", "code": "Lactate"})

    # Simulate a server restart: close the connection + reset the cache.
    if ehr_db._shared is not None:
        ehr_db._shared.close()
    ehr_db._shared = None
    ehr_db._db_ready = False
    # Drop the in-memory mirrors too, so the only way the data can come
    # back is from disk.
    ehr_db._mem.clear()
    ehr_db._mem_seeds.clear()

    # Reconnect (lazy) and read back.
    proj = ehr_db.fold(sid)
    assert proj["event_count"] == 2, "events did not survive the restart"
    assert len(proj["notes"]) == 1
    assert proj["notes"][0]["body"] == "Pre-restart note"
    assert len(proj["orders"]) == 1
    assert proj["orders"][0]["order"]["code"] == "Lactate"
    assert ehr_db.seed(sid)["mrn"] == "HLX-1"
    ehr_db.purge_session(sid)
