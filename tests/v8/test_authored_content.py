"""FR-013b G3 — authored-scenario persistence, persona synthesis, and the
library merge that makes an authored scenario first-class in the launch wizard."""
from __future__ import annotations

import pytest

from portal import authored_content as ac


@pytest.fixture(autouse=True)
def _isolated_authored(tmp_path, monkeypatch):
    """Each test writes to its own authored store (globals read at call time)."""
    d = tmp_path / "authored"
    monkeypatch.setattr(ac, "AUTHORED_DIR", d)
    monkeypatch.setattr(ac, "SCENARIOS_PATH", d / "scenarios.json")
    monkeypatch.setattr(ac, "PERSONAS_PATH", d / "personas.json")


def _draft(**over):
    d = {
        "name": "Sepsis on 4 West",
        "notes": "pre-brief",
        "patient": {"name": "Joe Diaz", "age": 68, "sex": "male",
                    "condition": "septic shock",
                    "history": "POD#2 sigmoid resection; BP 84/52; lactate 4.2.",
                    "baseline_vitals": {"BP": "112/68", "HR": "84"}},
        "scenario_text": "78M POD#2, febrile, BP 84/52.",
        "suggested_cast": [{"role": "Attending physician", "name": "Dr. Patel", "why": "leads care"},
                           {"role": "Wife", "name": "Mary", "why": "at bedside"}],
        "curriculum": {"touchpoints": ["recognize sepsis"]},
        "modules": ["sepsis"],
        "_inputs": {"patient_mode": "new", "patient": {}},
    }
    d.update(over)
    return d


# ── synthesis + persistence ─────────────────────────────────────────────────

def test_create_from_draft_new_patient_synthesizes_personas():
    rec = ac.create_from_draft(_draft())
    assert rec["id"] and rec["name"] == "Sepsis on 4 West"
    assert rec["source"] == "authored"
    by_id = {p["id"]: p for p in ac.list_personas()}
    pat = by_id[rec["personas"][0]]                    # patient is first
    assert pat["roleGroup"] == "Patient"               # so the wizard picks it
    assert pat["name"] == "Joe Diaz"
    assert pat["ageRange"] == "68"                      # → EHR DOB
    assert pat["condition"] == "septic shock"          # → EHR condition detect
    assert len(rec["personas"]) == 3                   # patient + 2 cast
    cast_groups = [by_id[pid]["roleGroup"] for pid in rec["personas"][1:]]
    assert "Family" in cast_groups                     # "Wife" mapped to Family
    assert ac.get_scenario(rec["id"]) is not None


def test_create_from_draft_library_patient_references_not_synthesizes():
    rec = ac.create_from_draft(_draft(
        _inputs={"patient_mode": "library", "patient": {"persona_id": "P-014"}}))
    assert rec["personas"][0] == "P-014"               # referenced, not synthesized
    assert "P-014" not in [p["id"] for p in ac.list_personas()]
    assert len(rec["personas"]) == 3                   # P-014 + 2 cast


def test_create_from_draft_requires_name_and_history():
    with pytest.raises(ValueError):
        ac.create_from_draft(_draft(name=""))
    with pytest.raises(ValueError):
        ac.create_from_draft(_draft(patient={"history": ""}))


def test_remove_scenario():
    rec = ac.create_from_draft(_draft())
    assert ac.remove_scenario(rec["id"]) is True
    assert ac.get_scenario(rec["id"]) is None
    assert ac.remove_scenario(rec["id"]) is False


# ── library merge (first-class in the wizard) ───────────────────────────────

def test_library_merges_authored_scenarios_and_personas():
    rec = ac.create_from_draft(_draft())
    from portal import library
    assert rec["id"] in [s["id"] for s in library.list_sample_scenarios()]
    assert rec["personas"][0] in [p["id"] for p in library.list_personas()]
    assert library.get_persona(rec["personas"][0])["roleGroup"] == "Patient"
    # static catalog still intact (authored is additive, not replacing)
    assert len(library.list_sample_scenarios()) > 1


def test_wizard_patient_of_resolves_authored_patient():
    """Replicate server.mission_control_console._patient_of over an authored
    scenario — it must pick the synthesized roleGroup=='Patient' persona."""
    rec = ac.create_from_draft(_draft())
    from portal import library
    by_id = {p["id"]: p for p in library.list_personas()}

    def patient_of(personas):
        for pid in personas:
            if (by_id.get(pid, {}).get("roleGroup") or "") == "Patient":
                return pid
        return personas[0] if personas else None

    assert patient_of(rec["personas"]) == rec["personas"][0]


# ── save API (auth + round-trip into the wizard catalog) ────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("MEDSIM_RESUME", "0")
    from portal import auth, control_room, credentials, server as server_mod
    sb = fake_home / ".medsim"
    sb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sb)
    monkeypatch.setattr(credentials, "VAULT_PATH", sb / "vault.enc")
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize("test_passwd_xyz_8chars")
    vault = credentials.unlock("test_passwd_xyz_8chars")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def test_api_save_roundtrip_appears_in_wizard(client):
    r = client.post("/api/scenario-studio/save", json=_draft())
    assert r.status_code == 200, r.text
    sid = r.json()["scenario"]["id"]
    assert len(r.json()["scenario"]["personas"]) == 3
    from portal import library
    assert sid in [s["id"] for s in library.list_sample_scenarios()]


def test_api_save_rejects_bad_draft(client):
    assert client.post("/api/scenario-studio/save",
                       json={"name": "", "patient": {}}).status_code == 400


def test_api_save_requires_instructor_auth(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.post("/api/scenario-studio/save",
                       json=_draft()).status_code in (401, 403)


def test_scenario_studio_page_renders(client):
    r = client.get("/portal/scenario-studio")
    assert r.status_code == 200
    assert "Scenario Studio" in r.text
    assert "/api/scenario-studio/generate" in r.text     # JS wired
    assert "/api/scenario-studio/save" in r.text
