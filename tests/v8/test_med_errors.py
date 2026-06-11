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


# ── S2: document vector ────────────────────────────────────────────────────────

import copy
import json as _json


@pytest.fixture
def doc_session(monkeypatch):
    """Grounded session with an IN-MEMORY chart store standing in for ehr_db:
    seed() hands out deep copies (like the DB), update_seed() commits + counts."""
    from portal import ehr_db
    cond = _condition_with_parseable_doses()
    med_orders.init_session(SID, cond)
    store = {
        "seed": {
            "allergies": [{"substance": "Penicillin", "reaction": "rash"}],
            "medications": [
                {"name": "Heparin gtt", "dose": "see order", "route": "IV",
                 "frequency": "cont", "status": "active"},
                {"name": "Aspirin", "dose": "81 mg", "route": "PO",
                 "frequency": "daily", "status": "active"},
            ],
            "notes_recent": [
                {"note_id": "n_admit_hp", "note_type": "Admission H&P",
                 "author": "Admitting provider", "ts": "T-12h",
                 "body": "Admitted overnight.", "signed": True},
            ],
            "vitals_baseline": [{"hr": "80"}],
        },
        "writes": 0,
    }
    monkeypatch.setattr(ehr_db, "seed",
                        lambda sid: copy.deepcopy(store["seed"]) if sid == SID else {})

    def _update(sid, new_seed):
        assert sid == SID
        store["seed"] = copy.deepcopy(new_seed)
        store["writes"] += 1
    monkeypatch.setattr(ehr_db, "update_seed", _update)
    monkeypatch.setattr(ehr_db, "orders", lambda sid: [])
    yield SID, store
    med_orders._SESSION_MEDS.pop(SID, None)
    med_errors.clear_session(SID)


def _arm_doc(sid: str, err_type: str, encounter: str) -> dict:
    cand = med_errors.suggest(sid, err_type, "document", encounter)[0]
    return med_errors.arm(sid, err_type=err_type, vector="document",
                          encounter=encounter, payload=cand)


def test_report_encounter_plants_one_sbar_note_only(doc_session) -> None:
    sid, store = doc_session
    before = copy.deepcopy(store["seed"])
    rec = _arm_doc(sid, "allergy", "report")
    after = store["seed"]
    assert store["writes"] == 1 and rec["status"] == "delivered"
    notes = after["notes_recent"]
    assert len(notes) == len(before["notes_recent"]) + 1
    staged = notes[-1]
    assert staged["note_type"] == "Shift Handoff (SBAR)"
    assert rec["payload"]["drug"] in staged["body"]
    assert "allerg" not in staged["body"].lower()      # never self-announcing
    # Exactly ONE artifact changed — everything else byte-identical.
    for key in before:
        if key != "notes_recent":
            assert _json.dumps(after[key], sort_keys=True) == \
                   _json.dumps(before[key], sort_keys=True), key


def test_charting_encounter_contradicts_mar_in_a_note(doc_session) -> None:
    sid, store = doc_session
    rec = _arm_doc(sid, "wrong_dose", "charting")
    staged = store["seed"]["notes_recent"][-1]
    assert staged["note_type"] == "Progress"
    assert rec["payload"]["wrong_dose"] in staged["body"]
    # The MAR (the truth) is untouched.
    assert all(rec["payload"]["wrong_dose"] != m["dose"]
               for m in store["seed"]["medications"])


def test_prep_encounter_mutates_the_mar_row(doc_session) -> None:
    sid, store = doc_session
    rec = _arm_doc(sid, "wrong_dose", "prep")
    p = rec["payload"]
    rows = store["seed"]["medications"]
    planted = [r for r in rows if med_errors._name_match(p["drug"], r["name"])]
    assert planted and planted[0]["dose"] == p["wrong_dose"]
    assert store["seed"]["notes_recent"][-1]["note_id"] == "n_admit_hp"  # notes untouched


def test_med_pass_encounter_plants_due_now_interaction_row(doc_session) -> None:
    sid, store = doc_session
    rec = _arm_doc(sid, "interaction", "med_pass")
    p = rec["payload"]
    row = next(r for r in store["seed"]["medications"]
               if med_errors._name_match(p["new_med"], r["name"]))
    assert "due this pass" in row["frequency"]


def test_admin_expired_tags_the_existing_row(doc_session) -> None:
    sid, store = doc_session
    cands = med_errors.suggest(sid, "admin", "document", "prep")
    expired = next(c for c in cands if c["kind"] == "expired")
    med_errors.arm(sid, err_type="admin", vector="document",
                   encounter="prep", payload=expired)
    row = next(r for r in store["seed"]["medications"]
               if med_errors._name_match(expired["drug"], r["name"]))
    assert "lot expired" in row["dose"]


def test_disarm_restores_chart_byte_for_byte(doc_session) -> None:
    sid, store = doc_session
    pristine = _json.dumps(store["seed"], sort_keys=True)
    rec = _arm_doc(sid, "interaction", "med_pass")
    assert _json.dumps(store["seed"], sort_keys=True) != pristine
    assert med_errors.disarm(sid, rec["id"])
    assert _json.dumps(store["seed"], sort_keys=True) == pristine
    assert store["writes"] == 2                        # one plant, one restore


def test_disarm_restores_an_originally_absent_key(doc_session) -> None:
    sid, store = doc_session
    del store["seed"]["notes_recent"]
    rec = _arm_doc(sid, "allergy", "charting")
    assert "notes_recent" in store["seed"]
    med_errors.disarm(sid, rec["id"])
    assert "notes_recent" not in store["seed"]


def test_resolve_keeps_the_chart_as_the_student_saw_it(doc_session) -> None:
    sid, store = doc_session
    rec = _arm_doc(sid, "wrong_dose", "med_pass")
    mutated = _json.dumps(store["seed"], sort_keys=True)
    med_errors.resolve(sid, rec["id"], "missed", note="debrief topic")
    assert _json.dumps(store["seed"], sort_keys=True) == mutated


def test_verbal_arms_never_touch_the_chart(doc_session) -> None:
    sid, store = doc_session
    cand = med_errors.suggest(sid, "wrong_dose", "verbal", "med_pass")[0]
    med_errors.arm(sid, err_type="wrong_dose", vector="verbal",
                   encounter="med_pass", payload=cand)
    assert store["writes"] == 0


# ── S3: verbal vector + STT interplay ──────────────────────────────────────────

DOCTOR = {"role": "Attending physician"}
PHARMACIST = {"role": "Clinical pharmacist"}
PATIENT = {"role": "Patient"}


def _arm_verbal(sid: str, err_type: str = "transcription") -> dict:
    cand = med_errors.suggest(sid, err_type, "verbal", "med_pass")[0]
    return med_errors.arm(sid, err_type=err_type, vector="verbal",
                          encounter="med_pass", payload=cand)


def test_verbal_block_goes_only_to_the_ordering_character(doc_session) -> None:
    sid, _ = doc_session
    rec = _arm_verbal(sid)
    block = med_errors.prompt_block_for(sid, DOCTOR)
    assert rec["payload"]["wrong_drug"] in block
    assert rec["payload"]["intended_drug"] in block
    assert "STAGED VERBAL ORDER" in block
    assert med_errors.prompt_block_for(sid, PHARMACIST) == ""
    assert med_errors.prompt_block_for(sid, PATIENT) == ""


def test_verbal_block_carries_containment_and_correction_arc(doc_session) -> None:
    sid, _ = doc_session
    rec = _arm_verbal(sid, "wrong_dose")
    block = med_errors.prompt_block_for(sid, DOCTOR)
    assert rec["payload"]["wrong_dose"] in block          # the staged slip
    assert rec["payload"]["right_dose"] in block          # the correction path
    assert "ONLY error you introduce" in block            # containment rule
    assert "Do not invent" in block
    assert "never hint" in block


def test_doctor_reply_with_the_marker_stamps_delivered(doc_session) -> None:
    sid, _ = doc_session
    rec = _arm_verbal(sid)
    wrong = rec["payload"]["wrong_drug"]
    # Unrelated reply: still armed.
    med_errors.note_character_reply(sid, "P-X", "Let's reassess in an hour.",
                                    role="doctor")
    assert med_errors.get(sid, rec["id"])["status"] == "armed"
    # The PATIENT saying the drug name must NOT stamp delivery.
    med_errors.note_character_reply(sid, "P-Y", f"I think I was on {wrong} once?",
                                    role=None if False else "patient")
    assert med_errors.get(sid, rec["id"])["status"] == "armed"
    # The doctor speaking the staged order: delivered.
    med_errors.note_character_reply(
        sid, "P-X", f"Start {wrong} now, please.", role="doctor")
    got = med_errors.get(sid, rec["id"])
    assert got["status"] == "delivered" and got["delivered_at"] is not None


def test_block_persists_through_delivered_and_retires_on_resolve(doc_session) -> None:
    sid, _ = doc_session
    rec = _arm_verbal(sid)
    med_errors.note_character_reply(
        sid, "P-X", f"Give {rec['payload']['wrong_drug']}.", role="doctor")
    assert med_errors.prompt_block_for(sid, DOCTOR) != ""   # repeat-backs consistent
    med_errors.resolve(sid, rec["id"], "caught")
    assert med_errors.prompt_block_for(sid, DOCTOR) == ""   # retired after resolve


def test_vocab_extras_carry_both_sound_alike_names(doc_session) -> None:
    sid, _ = doc_session
    rec = _arm_verbal(sid)
    extras = med_errors.vocab_extras(sid)
    assert rec["payload"]["intended_drug"] in extras
    assert rec["payload"]["wrong_drug"] in extras           # never auto-correct
    med_errors.resolve(sid, rec["id"], "missed")
    assert med_errors.vocab_extras(sid) == []


def test_session_vocab_merges_staged_error_names(doc_session, monkeypatch) -> None:
    from portal import control_session, room_stt
    sid, _ = doc_session
    rec = _arm_verbal(sid)

    class _Sess:
        id = sid
    monkeypatch.setattr(control_session, "get_active", lambda: _Sess())
    vocab = room_stt.session_vocab()
    assert vocab is not None
    assert rec["payload"]["wrong_drug"] in vocab


# ── S4: patient impact ─────────────────────────────────────────────────────────

@pytest.fixture
def impact_session(doc_session, monkeypatch):
    """doc_session + captured vitals events + a seeded vitals baseline."""
    from portal import ehr_db
    sid, store = doc_session
    store["seed"]["vitals_baseline"] = [
        {"time": "t-4h", "hr": "82", "rr": "16", "spo2": "97",
         "bp": "118/74", "pain": "2", "t": "37.0"},
    ]
    events = []
    monkeypatch.setattr(
        ehr_db, "append_event",
        lambda sid_, station, *, type, surface, payload:
            events.append({"station": station, "type": type,
                           "surface": surface, "payload": payload}) or 1)
    return sid, store, events


def _arm_allergy_with_impact(sid: str, severity: str = "moderate",
                             trigger: str = "manual", **kw) -> dict:
    cand = med_errors.suggest(sid, "allergy", "verbal", "med_pass")[0]
    return med_errors.arm(
        sid, err_type="allergy", vector="verbal", encounter="med_pass",
        payload=cand,
        impact={"profile": "anaphylaxis", "severity": severity,
                "trigger": trigger, **kw})


def test_impact_options_follow_the_curated_mapping(doc_session) -> None:
    sid, _ = doc_session
    a = _arm_verbal(sid, "wrong_dose")          # board doses → direction varies
    opts = med_errors.impact_options(sid, a["id"])
    allowed = med_errors.allowed_profiles("wrong_dose", a["payload"])
    assert [o["profile"] for o in opts] == allowed
    if a["payload"]["direction"] == "low":
        assert allowed == ["subtherapeutic"]
    else:
        assert "subtherapeutic" not in allowed
    # Allergy errors map to the anaphylaxis spectrum only.
    assert med_errors.allowed_profiles("allergy", {}) == ["anaphylaxis"]
    # Interaction maps by risk label.
    assert med_errors.allowed_profiles(
        "interaction", {"risk": "respiratory depression"}) == ["respiratory_depression"]


def test_arm_validates_impact_config(doc_session) -> None:
    sid, _ = doc_session
    cand = med_errors.suggest(sid, "allergy", "verbal", "med_pass")[0]
    with pytest.raises(ValueError):     # profile outside the curated set
        med_errors.arm(sid, err_type="allergy", vector="verbal",
                       encounter="med_pass", payload=cand,
                       impact={"profile": "bleeding", "severity": "mild",
                               "trigger": "manual"})
    with pytest.raises(ValueError):     # severe + auto needs confirmed=True
        med_errors.arm(sid, err_type="allergy", vector="verbal",
                       encounter="med_pass", payload=cand,
                       impact={"profile": "anaphylaxis", "severity": "severe",
                               "trigger": "on_administer"})
    rec = med_errors.arm(sid, err_type="allergy", vector="verbal",
                         encounter="med_pass", payload=cand,
                         impact={"profile": "anaphylaxis", "severity": "severe",
                                 "trigger": "on_administer", "confirmed": True})
    assert rec["impact"]["confirmed"] is True


def test_trigger_applies_vitals_and_patient_block(impact_session) -> None:
    sid, _, events = impact_session
    rec = _arm_allergy_with_impact(sid)
    assert med_errors.prompt_block_for(sid, PATIENT) == ""   # not yet triggered
    med_errors.trigger_impact(sid, rec["id"])
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "vitals.record" and ev["payload"]["source"] == "staged-impact"
    assert ev["payload"]["hr"] == "112"                      # moderate anaphylaxis
    block = med_errors.prompt_block_for(sid, PATIENT)
    assert "PATIENT STATE CHANGE" in block and "hives" in block
    assert "Do NOT name a diagnosis" in block
    assert med_errors.prompt_block_for(sid, PHARMACIST) == ""
    with pytest.raises(ValueError):                          # no double trigger
        med_errors.trigger_impact(sid, rec["id"])


def test_severe_manual_trigger_demands_second_confirmation(impact_session) -> None:
    sid, _, events = impact_session
    rec = _arm_allergy_with_impact(sid, severity="severe")
    with pytest.raises(ValueError):
        med_errors.trigger_impact(sid, rec["id"])
    med_errors.trigger_impact(sid, rec["id"], confirm_severe=True)
    assert events[0]["payload"]["bp"] == "78/44"


def test_stabilize_restores_baseline_and_retires_the_script(impact_session) -> None:
    sid, _, events = impact_session
    rec = _arm_allergy_with_impact(sid)
    med_errors.trigger_impact(sid, rec["id"])
    med_errors.stabilize(sid, rec["id"])
    assert len(events) == 2
    back = events[1]["payload"]
    assert back["source"] == "stabilized"
    assert back["hr"] == "82" and back["bp"] == "118/74"     # captured baseline
    assert med_errors.prompt_block_for(sid, PATIENT) == ""
    with pytest.raises(ValueError):
        med_errors.stabilize(sid, rec["id"])                 # once


def test_administration_hook_fires_only_matching_auto_errors(impact_session) -> None:
    sid, _, events = impact_session
    manual = _arm_allergy_with_impact(sid, trigger="manual")
    auto = _arm_allergy_with_impact(sid, trigger="on_administer")
    drug = auto["payload"]["drug"]
    med_errors.note_med_administered(sid, "Acetaminophen 650 mg PO")
    assert events == [] and auto.get("impact_state") is None
    med_errors.note_med_administered(sid, f"{drug} 3.375 g IV")
    assert auto["impact_state"] is not None                  # auto fired
    assert manual.get("impact_state") is None                # manual untouched
    assert len(events) == 1


def test_resolved_error_cannot_fire_its_impact(impact_session) -> None:
    sid, _, events = impact_session
    rec = _arm_allergy_with_impact(sid)
    med_errors.resolve(sid, rec["id"], "caught")
    with pytest.raises(ValueError):
        med_errors.trigger_impact(sid, rec["id"])
    assert events == []


def test_failed_apply_stages_nothing(doc_session) -> None:
    sid, store = doc_session
    # An admin error whose drug is NOT on the MAR can't be planted — atomic.
    bogus = {"type": "admin", "vector": "document", "encounter": "prep",
             "kind": "expired", "drug": "Zzz-not-here", "days": 30,
             "display": "Zzz: stock expired"}
    with pytest.raises(ValueError):
        med_errors.arm(sid, err_type="admin", vector="document",
                       encounter="prep", payload=bogus)
    assert med_errors.state(sid)["errors"] == []
    assert store["writes"] == 0
