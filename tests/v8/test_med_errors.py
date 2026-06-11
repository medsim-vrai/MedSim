"""FR-008 S1 — staged-medication-error catalog + arming engine.

Boundedness is the property under test: suggestions only from catalog ∩ session,
taxonomy-invalid axes rejected, impact locked until S4, lifecycle audited."""
from __future__ import annotations

import pytest

from portal import med_errors, med_orders


SID = "s-mederr-test"


def _condition_with_parseable_doses() -> str:
    """Pick an authored condition whose board carries at least one numeric dose."""
    for key, entry in med_orders.catalog().items():
        if key.startswith("_"):
            continue
        for opt in entry.get("primary") or []:
            if med_errors._NUM_RE.search(str(opt.get("dose") or "")):
                return key
    raise AssertionError("no condition with numeric doses — formulary changed?")


@pytest.fixture
def session(monkeypatch):
    """A grounded fake session: real med board + a stubbed chart (MAR with
    Heparin + Aspirin; documented Penicillin allergy)."""
    from portal import ehr_db
    cond = _condition_with_parseable_doses()
    med_orders.init_session(SID, cond)
    monkeypatch.setattr(ehr_db, "seed", lambda sid: {
        "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
        "meds": [
            {"name": "Heparin gtt", "dose": "—", "frequency": "cont"},
            {"name": "Aspirin", "dose": "81 mg", "frequency": "PO daily"},
        ],
    } if sid == SID else {})
    monkeypatch.setattr(ehr_db, "orders", lambda sid: [])
    yield SID
    med_orders._SESSION_MEDS.pop(SID, None)
    med_errors.clear_session(SID)


# ── catalog ────────────────────────────────────────────────────────────────────

def test_catalog_is_draft_gated_and_well_formed() -> None:
    cat = med_errors.catalog()
    assert "DRAFT" in cat["_meta"]["status"]
    assert "CLINICAL REVIEW" in cat["_meta"]["status"]
    for p in cat["sound_alike_pairs"]:
        assert p["a"] != p["b"]
    for t in cat["dose_transforms"]:
        assert t["direction"] in ("high", "low")
    for e in cat["allergy_map"]:
        assert e["allergen"] and e["meds"]


# ── dose transforms ────────────────────────────────────────────────────────────

def test_dose_transforms() -> None:
    x10 = {"op": "mul", "factor": 10}
    half = {"op": "mul", "factor": 0.5}
    swap = {"op": "unit_swap", "from": "mcg", "to": "mg"}
    assert med_errors.transform_dose("0.5 mg", x10) == "5 mg"
    assert med_errors.transform_dose("10 mg", half) == "5 mg"
    assert med_errors.transform_dose("12.5 mg PO", x10) == "125 mg PO"
    assert med_errors.transform_dose("25 mcg", swap) == "25 mg"
    assert med_errors.transform_dose("25 mg", swap) is None      # unit absent
    assert med_errors.transform_dose("—", x10) is None           # unparseable
    assert med_errors.transform_dose("", x10) is None


# ── suggestion grounding ───────────────────────────────────────────────────────

def test_transcription_suggestions_grounded_in_session_meds(session) -> None:
    out = med_errors.suggest(session, "transcription", "verbal", "report")
    assert out, "MAR carries Heparin — the Heparin/Hespan pair must fire"
    for c in out:
        found, _ = med_errors._on_session(session, c["intended_drug"])
        assert found, f"suggested intended drug {c['intended_drug']} not on session"
        assert c["display"]


def test_allergy_suggestions_require_documented_allergy(session, monkeypatch) -> None:
    out = med_errors.suggest(session, "allergy", "document", "charting")
    assert out, "documented Penicillin allergy + formulary Pip-tazo must fire"
    assert any(c["allergen"] == "Penicillin" for c in out)
    # Remove the documented allergy → zero suggestions (never auto-document one).
    from portal import ehr_db
    monkeypatch.setattr(ehr_db, "seed", lambda sid: {"allergies": [], "meds": []})
    assert med_errors.suggest(session, "allergy", "document", "charting") == []


def test_interaction_suggestions_need_one_member_on_session(session) -> None:
    out = med_errors.suggest(session, "interaction", "document", "prep")
    assert out, "Heparin on MAR + Ibuprofen in formulary must fire"
    assert any(
        med_errors._name_match("Heparin", c["on_med"])
        or med_errors._name_match("Aspirin", c["on_med"])
        for c in out)


def test_wrong_dose_suggestions_come_from_the_board(session) -> None:
    out = med_errors.suggest(session, "wrong_dose", "verbal", "med_pass")
    assert out
    board = {it["drug"] for it in med_orders.get_state(session)["items"]}
    for c in out:
        assert c["drug"] in board
        assert c["wrong_dose"] != c["right_dose"]


def test_suggestions_are_deterministic_per_axes(session) -> None:
    a = med_errors.suggest(session, "wrong_dose", "verbal", "med_pass")
    b = med_errors.suggest(session, "wrong_dose", "verbal", "med_pass")
    assert a == b


# ── taxonomy enforcement ───────────────────────────────────────────────────────

def test_taxonomy_rejects_invalid_axis_combinations(session) -> None:
    with pytest.raises(ValueError):   # transcription is verbal-only
        med_errors.suggest(session, "transcription", "document", "report")
    with pytest.raises(ValueError):   # admin is document-only
        med_errors.suggest(session, "admin", "verbal", "med_pass")
    with pytest.raises(ValueError):
        med_errors.suggest(session, "wrong_dose", "verbal", "lunch")
    with pytest.raises(ValueError):
        med_errors.suggest(session, "banana", "verbal", "report")


# ── lifecycle ──────────────────────────────────────────────────────────────────

def test_arm_resolve_disarm_lifecycle(session) -> None:
    cand = med_errors.suggest(session, "wrong_dose", "verbal", "med_pass")[0]
    rec = med_errors.arm(session, err_type="wrong_dose", vector="verbal",
                         encounter="med_pass", payload=cand, note="S1 drill")
    assert rec["status"] == "armed" and rec["id"] == "e1"
    assert rec["snapshot"] is None and rec["impact"] is None
    assert med_errors.state(session)["errors"][0]["payload"]["display"]

    assert med_errors.resolve(session, "e1", "caught", note="student flagged dose")
    got = med_errors.get(session, "e1")
    assert got["status"] == "resolved" and got["outcome"] == "caught"
    assert got["resolved_at"] is not None

    assert med_errors.disarm(session, "e1")
    assert med_errors.state(session)["errors"] == []
    assert not med_errors.disarm(session, "e1")          # gone is gone


def test_arm_rejects_impact_until_s4_and_bad_outcomes(session) -> None:
    cand = med_errors.suggest(session, "wrong_dose", "verbal", "med_pass")[0]
    with pytest.raises(ValueError):
        med_errors.arm(session, err_type="wrong_dose", vector="verbal",
                       encounter="med_pass", payload=cand,
                       impact={"consequence": "anaphylaxis"})
    with pytest.raises(ValueError):
        med_errors.arm(session, err_type="wrong_dose", vector="verbal",
                       encounter="med_pass", payload={})  # no display
    rec = med_errors.arm(session, err_type="wrong_dose", vector="verbal",
                         encounter="med_pass", payload=cand)
    with pytest.raises(ValueError):
        med_errors.resolve(session, rec["id"], "shrugged")


def test_unarmed_sessions_have_empty_state() -> None:
    assert med_errors.state("never-touched")["errors"] == []
