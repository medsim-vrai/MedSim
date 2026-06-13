"""FR-009 H1 — handoff context-pack generator.

The pack is the per-patient ground truth (AI knowledge = rubric = debrief
artifact). These tests pin: a complete golden pack, the severity mapping, the
staged-error join, tolerance of a missing chart section, and the vocab."""
from __future__ import annotations

import pytest

from portal import handoff


# A fictional fully-seeded chart (the Margaret-Hale / pneumonia shape from the
# FR-009 samples workbook).
HAYES_SEED = {
    "name": "Margaret Hale",
    "persona_id": "P-099",
    "chief_complaint": "community-acquired pneumonia",
    "condition": "pneumonia",
    "code_status": "Full Code",
    "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
    "problem_list": [{"name": "CAP (right lower lobe)"}, {"name": "Hypertension"}],
    "medications": [
        {"name": "Ceftriaxone", "dose": "1 g", "route": "IV", "frequency": "q24h"},
        {"name": "Azithromycin", "dose": "500 mg", "route": "PO", "frequency": "daily"},
        {"name": "Heparin", "dose": "5000 units", "route": "SC", "frequency": "q8h"},
    ],
    "vitals_baseline": [
        {"time": "t-12h", "t": "38.9", "hr": "104", "rr": "24", "bp": "118/74", "spo2": "92"},
        {"time": "t-8h",  "t": "38.5", "hr": "98",  "rr": "22", "bp": "120/76", "spo2": "93"},
        {"time": "t-4h",  "t": "38.1", "hr": "92",  "rr": "22", "bp": "128/76", "spo2": "94"},
    ],
    "labs_recent": [{"name": "WBC", "v": "14.2", "flag": "H"}],
    "iv_fluids": [{"name": "20G PIV", "site": "left forearm"}],
    "safety_class": "fall_risk",
    "altered_state": None,
}


@pytest.fixture
def chart(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    store = {"seed": dict(HAYES_SEED)}
    monkeypatch.setattr(ehr_db, "seed", lambda sid: dict(store["seed"]))
    monkeypatch.setattr(ehr_db, "fold",
                        lambda sid: {"orders": [{"label": "Blood cultures x2"}]})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    return store


def test_golden_pack_has_all_eleven_elements(chart):
    pack = handoff.build_pack("s1", now=1000.0)
    assert set(pack["elements"]) == {e[0] for e in handoff.ELEMENTS}
    assert len(pack["elements"]) == 11
    assert pack["patient"]["name"] == "Margaret Hale"
    assert pack["generated_at"] == 1000.0
    # High-risk flags match the model.
    for eid, el in pack["elements"].items():
        assert el["high_risk"] == (eid in handoff.HIGH_RISK)


def test_high_risk_content_is_present_and_correct(chart):
    el = handoff.build_pack("s1")["elements"]
    # Allergies + code status both in Background (the #1 high-risk pair).
    bg = el["background"]["content"]
    assert "Penicillin" in bg and "Full Code" in bg
    # The MAR surfaces meds + flags the high-alert one.
    meds = el["meds"]["content"]
    assert "Ceftriaxone" in meds and "Heparin" in meds and "high-alert" in meds
    # Pending pulls the open order.
    assert "Blood cultures" in el["pending"]["content"]
    # Synthesis + transfer carry the expectation (scored from transcript later).
    assert "read" in el["synthesis"]["content"].lower()
    assert "responsibility" in el["transfer"]["content"].lower()


def test_severity_mapping():
    # Worsening condition (sepsis) → unstable.
    assert handoff.severity_for({"condition": "sepsis",
        "vitals_baseline": [{"hr": "120", "rr": "28", "bp": "85/50", "spo2": "90"}]}) == "unstable"
    # Flat baseline, normal vitals → stable.
    assert handoff.severity_for({"condition": "stable_baseline",
        "vitals_baseline": [{"hr": "72", "rr": "14", "bp": "120/78", "spo2": "98"}]}) == "stable"
    # One abnormal vital on a non-worsening condition → watcher.
    assert handoff.severity_for({"condition": "stable_baseline",
        "vitals_baseline": [{"hr": "72", "rr": "14", "bp": "120/78", "spo2": "90"}]}) == "watcher"
    # Empty chart never raises.
    assert handoff.severity_for({}) in ("stable", "watcher", "unstable")


def test_staged_error_sets_the_discrepancy_probe(chart, monkeypatch):
    from portal import med_errors
    assert handoff.build_pack("s1")["staged_discrepancy"] is False
    monkeypatch.setattr(med_errors, "state",
                        lambda sid: {"errors": [{"status": "armed", "payload": {}}]})
    assert handoff.build_pack("s1")["staged_discrepancy"] is True
    # A resolved error does NOT keep the probe lit.
    monkeypatch.setattr(med_errors, "state",
                        lambda sid: {"errors": [{"status": "resolved", "payload": {}}]})
    assert handoff.build_pack("s1")["staged_discrepancy"] is False


def test_vocab_collects_drugs_and_allergens(chart):
    vocab = handoff.pack_vocab(handoff.build_pack("s1"))
    assert "Ceftriaxone" in vocab and "Heparin" in vocab
    assert "Penicillin" in vocab                    # allergen rides along
    assert len(vocab) == len(set(v.lower() for v in vocab))  # deduped


def test_missing_chart_section_degrades_never_raises(monkeypatch):
    from portal import ehr_db, med_orders, med_errors
    # A near-empty chart (only a name) — every element must still resolve.
    monkeypatch.setattr(ehr_db, "seed", lambda sid: {"name": "Doe"})
    monkeypatch.setattr(ehr_db, "fold", lambda sid: {})
    monkeypatch.setattr(med_orders, "get_state", lambda sid: None)
    monkeypatch.setattr(med_errors, "state", lambda sid: {"errors": []})
    pack = handoff.build_pack("empty")
    assert len(pack["elements"]) == 11
    assert pack["elements"]["background"]["content"]   # non-empty (NKDA / defaults)
    assert pack["elements"]["pending"]["content"] == "none documented"
    assert pack["_vocab"] == []


def test_seed_access_failure_yields_a_safe_empty_pack(monkeypatch):
    from portal import ehr_db
    def _boom(sid):
        raise RuntimeError("db down")
    monkeypatch.setattr(ehr_db, "seed", _boom)
    pack = handoff.build_pack("s1")          # must not raise
    assert len(pack["elements"]) == 11
    assert pack["patient"]["name"] == "(unknown)"
