"""FR-013b — Scenario Studio engine: prompt assembly, JSON parsing, draft
normalization (all pure/offline), plus the generate API (auth + wiring)."""
from __future__ import annotations

import pytest

from portal import local_context as lc
from portal import scenario_gen as sg


@pytest.fixture(autouse=True)
def _isolated_library(tmp_path, monkeypatch):
    """Isolate the local-context library so build_prompt's active_items() is
    empty by default and tests control it (the store reads module globals at
    call time)."""
    monkeypatch.setattr(lc, "LIBRARY_DIR", tmp_path)
    monkeypatch.setattr(lc, "LIBRARY_PATH", tmp_path / "library.json")


# ── coerce_inputs ───────────────────────────────────────────────────────────

def test_coerce_inputs_defaults_and_parsing():
    out = sg.coerce_inputs({"premise": "post-op sepsis",
                            "objectives": "recognize sepsis\n- start the bundle"})
    assert out["premise"] == "post-op sepsis"
    assert out["objectives"] == ["recognize sepsis", "start the bundle"]   # bullet stripped
    assert out["patient_mode"] == "new"          # default
    assert out["acuity"] == "deteriorating"      # default
    assert out["use_local_overlay"] is True      # default


# ── build_prompt (pure) ─────────────────────────────────────────────────────

def test_build_prompt_includes_premise_objectives_and_local_factors():
    inputs = sg.coerce_inputs({
        "premise": "78M POD#2 sigmoid resection, febrile",
        "objectives": ["recognize the sepsis trend"],
        "setting": "Med-surg floor",
        "local_factors": {
            "standing_orders": "Lactate q2h until normalized.",
            "population_issues": "High COPD prevalence in our catchment.",
            "patient_features": "Frail, hard-of-hearing elders.",
        },
    })
    system, user = sg.build_prompt(inputs)
    assert "STRICT JSON" in system
    assert "78M POD#2 sigmoid resection" in user
    assert "recognize the sepsis trend" in user
    assert "Med-surg floor" in user
    assert "Lactate q2h until normalized." in user
    assert "High COPD prevalence" in user
    assert "Frail, hard-of-hearing elders." in user
    assert "LOCAL PRACTICE CONTEXT" in user


def test_build_prompt_folds_in_active_overlay_items_when_enabled():
    lc.add_item(type="medication", title="Norepi",
                content="First-line pressor here.", active=True)
    on = sg.build_prompt(sg.coerce_inputs(
        {"premise": "shock", "use_local_overlay": True}))[1]
    off = sg.build_prompt(sg.coerce_inputs(
        {"premise": "shock", "use_local_overlay": False}))[1]
    assert "Norepi: First-line pressor here." in on
    assert "Norepi" not in off


def test_build_prompt_new_vs_library_patient():
    new = sg.build_prompt(sg.coerce_inputs(
        {"premise": "x", "patient_mode": "new",
         "patient": {"name": "Joe Diaz", "age": 68, "sex": "male"}}))[1]
    assert "create a NEW patient" in new
    assert "Joe Diaz" in new and "age 68" in new

    lib = sg.build_prompt(sg.coerce_inputs(
        {"premise": "x", "patient_mode": "library",
         "patient": {"persona_id": "P-014"}}))[1]
    assert "existing library patient 'P-014'" in lib


# ── extract_json (pure) ─────────────────────────────────────────────────────

def test_extract_json_plain_fenced_and_prose():
    assert sg.extract_json('{"name": "A"}')["name"] == "A"
    assert sg.extract_json('```json\n{"name": "B"}\n```')["name"] == "B"
    assert sg.extract_json('Here you go:\n{"name": "C"}\nHope that helps')["name"] == "C"
    with pytest.raises(ValueError):
        sg.extract_json("no json here")


# ── normalize_draft (pure) ──────────────────────────────────────────────────

def test_normalize_draft_coerces_and_defaults():
    d = sg.normalize_draft({
        "name": "Sepsis on 4 West",
        "notes": "pre-brief",
        "patient": {"name": "Joe", "age": "68", "sex": "male",
                    "condition": "septic shock",
                    "history": "POD#2; BP 84/52; lactate 4.2.",
                    "baseline_vitals": {"BP": "112/68", "HR": "84", "junk": ""}},
        "vitals_timeline": [{"t_minutes": "0", "vitals": {"BP": "112/68"}},
                            {"t_minutes": "bad", "vitals": {"BP": "x"}}],   # dropped
        "suggested_cast": [{"role": "Attending", "name": "Dr. Patel", "shared": True},
                           {"name": "no role"}],                            # dropped
        "curriculum": {"touchpoints": ["recognize sepsis", "  ", "start bundle"]},
        "treatment_path": "fluids\nantibiotics",
        "modules": ["sepsis"],
    })
    assert d["patient"]["age"] == 68                       # coerced to int
    assert d["patient"]["baseline_vitals"] == {"BP": "112/68", "HR": "84"}
    assert len(d["vitals_timeline"]) == 1                  # bad row dropped
    assert d["vitals_timeline"][0]["t_minutes"] == 0
    assert [c["role"] for c in d["suggested_cast"]] == ["Attending"]
    assert d["suggested_cast"][0]["shared"] is True
    assert d["curriculum"]["touchpoints"] == ["recognize sepsis", "start bundle"]
    assert d["treatment_path"] == ["fluids", "antibiotics"]
    assert d["scenario_text"] == "POD#2; BP 84/52; lactate 4.2."   # defaults to history


def test_normalize_draft_requires_name_and_history():
    with pytest.raises(ValueError):
        sg.normalize_draft({"name": "", "patient": {"history": "x"}})
    with pytest.raises(ValueError):
        sg.normalize_draft({"name": "A", "patient": {"history": ""}})


def test_generate_requires_key_and_premise():
    with pytest.raises(ValueError):
        sg.generate({"premise": "x"}, api_key="")
    with pytest.raises(ValueError):
        sg.generate({"premise": ""}, api_key="sk-ant-dummy")


# ── generate API (auth + wiring) ────────────────────────────────────────────

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
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def test_api_generate_requires_instructor_auth(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.post("/api/scenario-studio/generate",
                       json={"premise": "x"}).status_code in (401, 403)


def test_api_generate_rejects_missing_premise(client):
    # dummy key present (vault), so we reach generate(), which rejects no premise
    assert client.post("/api/scenario-studio/generate", json={}).status_code == 400


def test_api_generate_returns_draft(client, monkeypatch):
    from portal import scenario_gen
    monkeypatch.setattr(scenario_gen, "generate",
                        lambda body, *, api_key: {"name": "Stub", "patient": {}})
    r = client.post("/api/scenario-studio/generate", json={"premise": "sepsis"})
    assert r.status_code == 200, r.text
    assert r.json()["draft"]["name"] == "Stub"
