"""FR-017 — scenario exchange: export/import round-trip, collision remapping,
support-document carriage, external-asset manifest, malformed-bundle rejection."""
from __future__ import annotations

import base64
import json

import pytest

from portal import authored_content, scenario_docs, scenario_exchange, scenarios


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolate every store the exchange touches."""
    monkeypatch.setattr(scenarios, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(scenarios, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(authored_content, "AUTHORED_DIR", tmp_path / "authored")
    monkeypatch.setattr(authored_content, "SCENARIOS_PATH", tmp_path / "authored" / "scenarios.json")
    monkeypatch.setattr(authored_content, "PERSONAS_PATH", tmp_path / "authored" / "personas.json")
    monkeypatch.setattr(scenario_docs, "DOCS_DIR", tmp_path / "scenario_docs")
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "characters").mkdir()
    return tmp_path


def _seed_scenario(sid="sepsis_demo", chars=("nurse_riley",), kb=()):
    for cid in chars:
        scenarios.save_character({"id": cid, "name": cid.replace("_", " ").title(),
                                  "role": "nurse", "voice": {"register": "calm"}})
    scenarios.save_scenario({"id": sid, "name": "Sepsis Demo",
                             "patient": {"age": 61, "sex": "M", "history": "postop D2"},
                             "characters": list(chars), "kb_scope": list(kb)})
    return sid


def test_export_bundles_scenario_characters_and_docs(sandbox):
    sid = _seed_scenario()
    scenario_docs.save_doc(sid, "labs.pdf", b"%PDF-1.4 fake", doc_type="lab",
                           purpose="initial labs", ai_mode="context")
    b = scenario_exchange.export_bundle(sid)
    assert b["_manifest"]["format_version"] == scenario_exchange.FORMAT_VERSION
    assert b["_manifest"]["checksum"].startswith("sha256:")
    assert b["scenario"]["id"] == sid
    assert [c["id"] for c in b["characters"]] == ["nurse_riley"]
    assert len(b["support_documents"]) == 1
    doc = b["support_documents"][0]
    assert base64.b64decode(doc["data_base64"]) == b"%PDF-1.4 fake"
    assert scenario_exchange.validate_bundle(b) == []


def test_export_unknown_scenario_is_none(sandbox):
    assert scenario_exchange.export_bundle("nope") is None


def test_kb_scope_travels_as_external_dependency(sandbox):
    sid = _seed_scenario(kb=("local_sepsis_protocol",))
    b = scenario_exchange.export_bundle(sid)
    ext = {(a["type"], a["id"]) for a in b["_manifest"]["external_assets"]}
    assert ("local_context", "local_sepsis_protocol") in ext


def test_round_trip_into_clean_install(sandbox, tmp_path, monkeypatch):
    sid = _seed_scenario()
    scenario_docs.save_doc(sid, "xray.png", b"\x89PNG fake", ai_mode="on_ask")
    bundle = scenario_exchange.export_bundle(sid)

    # "Second install": wipe the stores, then import.
    monkeypatch.setattr(scenarios, "SCENARIOS_DIR", tmp_path / "s2" / "scenarios")
    monkeypatch.setattr(scenarios, "CHARACTERS_DIR", tmp_path / "s2" / "characters")
    monkeypatch.setattr(scenario_docs, "DOCS_DIR", tmp_path / "s2" / "docs")
    (tmp_path / "s2" / "scenarios").mkdir(parents=True)
    (tmp_path / "s2" / "characters").mkdir(parents=True)

    report = scenario_exchange.import_bundle(bundle)
    assert report["scenario_id"] == sid                      # no collision → same id
    assert report["characters"][0]["action"] == "imported"
    assert report["documents"] == 1
    landed = scenarios.get_scenario(sid)
    assert landed["patient"]["history"] == "postop D2"
    assert scenarios.get_character("nurse_riley") is not None
    docs = scenario_docs.list_docs(sid)
    assert len(docs) == 1 and docs[0]["ai_mode"] == "on_ask"


def test_import_never_overwrites_scenario_id(sandbox):
    sid = _seed_scenario()
    bundle = scenario_exchange.export_bundle(sid)
    report = scenario_exchange.import_bundle(bundle)          # import onto itself
    assert report["scenario_id"] != sid                       # suffixed, not clobbered
    assert scenarios.get_scenario(sid)["name"] == "Sepsis Demo"      # original intact
    assert scenarios.get_scenario(report["scenario_id"]) is not None


def test_identical_character_links_different_character_remaps(sandbox):
    sid = _seed_scenario()
    bundle = scenario_exchange.export_bundle(sid)
    # identical character already present → linked
    r1 = scenario_exchange.import_bundle(json.loads(json.dumps(bundle)))
    assert r1["characters"][0]["action"] == "linked"
    # now the local character diverges → the import must NOT clobber it
    scenarios.save_character({"id": "nurse_riley", "name": "Nurse Riley",
                              "role": "nurse", "voice": {"register": "sharp"}})
    r2 = scenario_exchange.import_bundle(json.loads(json.dumps(bundle)))
    entry = r2["characters"][0]
    assert entry["as"] != "nurse_riley"
    assert scenarios.get_character("nurse_riley")["voice"]["register"] == "sharp"
    # the imported scenario references the REMAPPED id
    assert entry["as"] in scenarios.get_scenario(r2["scenario_id"])["characters"]
    assert any("review" in c or "renamed" in c for c in r2["checklist"])


def test_edited_bundle_imports_with_checksum_warning(sandbox):
    sid = _seed_scenario()
    bundle = scenario_exchange.export_bundle(sid)
    bundle["scenario"]["name"] = "Edited In Transit"
    report = scenario_exchange.import_bundle(bundle)
    assert any("checksum" in w for w in report["warnings"])
    assert scenarios.get_scenario(report["scenario_id"])["name"] == "Edited In Transit"


def test_malformed_bundles_rejected(sandbox):
    with pytest.raises(ValueError):
        scenario_exchange.import_bundle({"scenario": {"id": "x"}})     # no manifest
    with pytest.raises(ValueError):
        scenario_exchange.import_bundle(
            {"_manifest": {"format_version": "9.0"}, "scenario": {"id": "x", "name": "X"}})
    assert scenario_exchange.validate_bundle("not a dict")


# ── review fixes: traversal, datetime, doc-failure isolation, persona shape ──

def test_import_sanitizes_traversal_ids(sandbox):
    import types
    from portal import scenario_exchange as sx
    bundle = {
        "_manifest": {"format_version": "1.0"},
        "scenario": {"id": "../../evil", "name": "Evil", "characters": ["../../evilchar"]},
        "characters": [{"id": "../../evilchar", "name": "X", "role": "nurse"}],
    }
    report = sx.import_bundle(bundle)
    # nothing landed outside the stores
    for pth in list(scenarios.SCENARIOS_DIR.parent.rglob("*.yaml")):
        assert scenarios.SCENARIOS_DIR in pth.parents or scenarios.CHARACTERS_DIR in pth.parents, pth
    assert ".." not in report["scenario_id"] and "/" not in report["scenario_id"]
    assert scenarios.get_scenario(report["scenario_id"]) is not None


def test_export_handles_yaml_date_objects(sandbox):
    import datetime
    from portal import scenario_exchange as sx
    scenarios.save_character({"id": "c", "name": "C", "role": "nurse"})
    # simulate what yaml.safe_load yields for a bare date
    scenarios.SCENARIOS_DIR.joinpath("d.yaml").write_text(
        "id: d\nname: D\npatient:\n  dob: 1961-03-04\ncharacters: [c]\n")
    b = sx.export_bundle("d")
    assert b is not None and b["_manifest"]["checksum"].startswith("sha256:")
    assert sx._jdump(b)  # would raise TypeError on a raw json.dumps


def test_bad_document_is_skipped_not_aborting(sandbox):
    import base64
    from portal import scenario_exchange as sx
    sid = _seed_scenario()
    bundle = sx.export_bundle(sid)
    bundle["support_documents"] = [
        {"filename": "notes.txt", "data_base64": base64.b64encode(b"hi").decode()}]
    report = sx.import_bundle(bundle)                 # unsupported ext
    assert report["documents"] == 0
    assert any("notes.txt" in w for w in report["warnings"])
    assert scenarios.get_scenario(report["scenario_id"]) is not None   # scenario still landed


def test_persona_without_id_skipped_not_keyerror(sandbox):
    from portal import scenario_exchange as sx
    bundle = {"_manifest": {"format_version": "1.0"},
              "scenario": {"id": "s", "name": "S", "characters": []},
              "personas": [{"name": "no id here"}]}
    report = sx.import_bundle(bundle)                 # must not raise KeyError
    assert any("no id" in w for w in report["warnings"])
    assert scenarios.get_scenario(report["scenario_id"]) is not None
