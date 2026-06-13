"""V3 — ChartSeed builder unit tests.

For each of the 24 personas in the library, seed is non-empty, MRN is
unique, code status maps correctly. Also asserts the seed is
deterministic (same persona id → same MRN, name, etc.).
"""
from __future__ import annotations

from portal import ehr_seed, library


def test_seeds_are_non_empty_for_every_persona():
    seen_mrns: set[str] = set()
    seen_names: list[str] = []
    for p in library.list_personas():
        seed = ehr_seed.seed_from_persona(p, modules=[], scenario_text="")
        assert seed["mrn"], f"empty MRN for {p['id']}"
        assert seed["name"], f"empty name for {p['id']}"
        assert seed["dob"], f"empty DOB for {p['id']}"
        assert seed["code_status"] in ("Full Code", "DNR", "DNR/DNI"), \
            f"unexpected code_status for {p['id']}: {seed['code_status']}"
        assert seed["safety_class"] == p.get("safetyClass", "baseline")
        assert seed["mrn"] not in seen_mrns, f"MRN collision: {seed['mrn']} ({p['id']})"
        seen_mrns.add(seed["mrn"])
        seen_names.append(seed["name"])
    assert len(seen_mrns) == len(library.list_personas())


def test_seed_is_deterministic():
    p = library.list_personas()[0]
    a = ehr_seed.seed_from_persona(p, modules=[], scenario_text="")
    b = ehr_seed.seed_from_persona(p, modules=[], scenario_text="")
    assert a["mrn"] == b["mrn"]
    assert a["name"] == b["name"]
    assert a["dob"] == b["dob"]


def test_modules_drive_problem_list():
    p = library.get_persona("P-013")  # Mrs. Kowalski (geriatric patient)
    assert p is not None
    m22 = library.get_module("M22")   # Diabetes & DKA / HHS
    assert m22 is not None
    seed = ehr_seed.seed_from_persona(p, modules=[m22], scenario_text="")
    problem_names = " ".join(prob["name"].lower() for prob in seed["problem_list"])
    # M22 conditions include DKA/HHS/hypoglycemia/diabetic foot — at least one should land.
    assert any(k in problem_names for k in ("dka", "hhs", "hypogly", "diabetic")), \
        f"module-driven problems missing: got {problem_names!r}"


def test_high_risk_personas_keep_safety_class():
    delirium = library.get_persona("P-014")
    assert delirium is not None
    seed = ehr_seed.seed_from_persona(delirium, modules=[], scenario_text="")
    assert seed["safety_class"] == "high-risk"
    assert seed["altered_state"] == "delirium"


def test_mrn_format_per_ehr():
    p = library.list_personas()[0]
    assert ehr_seed.seed_from_persona(p, modules=[], scenario_text="", ehr_id="helix")["mrn"].startswith("HLX-")
    assert ehr_seed.seed_from_persona(p, modules=[], scenario_text="", ehr_id="cyrus")["mrn"].startswith("CY-")
    assert ehr_seed.seed_from_persona(p, modules=[], scenario_text="", ehr_id="meridian")["mrn"].startswith("MER-2026-")


# ── V5 Phase 2 — seed correctness ──────────────────────────────────────

def test_patient_name_keeps_proper_persona_names():
    """A persona with a proper name (Mr. Bennett, Mrs. Kowalski) must
    appear in the chart under THAT name — not a random invented one."""
    for pid, expect in [("P-012", "Mr. Bennett"), ("P-013", "Mrs. Kowalski"),
                        ("P-016", "Mr. Doyle"), ("P-019", "Mr. Kessler")]:
        p = library.get_persona(pid)
        seed = ehr_seed.seed_from_persona(p, modules=[], scenario_text="")
        assert seed["name"] == expect, f"{pid}: got {seed['name']!r}, want {expect!r}"


def test_given_name_persona_keeps_first_name():
    """'Adi (age 7)' → keeps 'Adi', gains a deterministic surname."""
    adi = library.get_persona("P-015")
    seed = ehr_seed.seed_from_persona(adi, modules=[], scenario_text="")
    assert seed["name"].split()[0] == "Adi", seed["name"]
    assert len(seed["name"].split()) == 2  # given + surname


def test_seed_carries_persona_identity_and_chief_complaint():
    p = library.get_persona("P-013")
    seed = ehr_seed.seed_from_persona(p, modules=[library.get_module("M22")],
                                      scenario_text="Reports polyuria and fatigue.")
    assert seed["persona_id"] == "P-013"
    assert seed["persona_label"] == "Mrs. Kowalski"
    assert seed["chief_complaint"], "chief complaint missing"


def test_scenario_text_flows_into_admit_note():
    """The free-form scenario the instructor wrote must appear in the
    pre-existing admission note so the chart matches the scenario."""
    p = library.get_persona("P-012")
    scenario = ("Postop day 1 status post laparoscopic cholecystectomy. "
                "58yo with hx HTN. Reports 8/10 RUQ pain.")
    seed = ehr_seed.seed_from_persona(p, modules=[], scenario_text=scenario)
    notes = seed["notes_recent"]
    assert len(notes) == 2, "expected admission H&P + nursing note"
    hp = next(n for n in notes if n["note_type"] == "Admission H&P")
    assert "cholecystectomy" in hp["body"], "scenario_text not in admit note"
    assert "Mr. Bennett" in hp["body"]
    # Encounter reason also reflects the scenario.
    assert "cholecystectomy" in seed["encounter"]["reason"].lower()


def test_altered_state_documented_in_note():
    """A delirium persona's chart should note the altered state."""
    p = library.get_persona("P-014")  # Mr. Hayes — hyperactive delirium
    seed = ehr_seed.seed_from_persona(p, modules=[], scenario_text="")
    bodies = " ".join(n["body"].lower() for n in seed["notes_recent"])
    assert "delirium" in bodies or "confused" in bodies

# ── 2026-06-13 bugfix — Medical Record showed the DOCTOR as the patient ──────
# A single-patient session that lists a clinician FIRST (e.g. a doctor added for
# the ordering loop) must still resolve the PATIENT for the chart, not [0].
from types import SimpleNamespace


def _find_by_rolegroup(group: str) -> str:
    for p in library.list_personas():
        if str(p.get("roleGroup") or "").strip().lower() == group.lower():
            return p["id"]
    raise AssertionError(f"no persona with roleGroup {group!r}")


def test_patient_resolved_role_aware_when_clinician_listed_first():
    patient = _find_by_rolegroup("Patient")
    clinician = _find_by_rolegroup("Clinician")
    # Clinician first, patient second, no explicit patient_persona_id (the v6
    # single-patient path never sets it).
    sess = SimpleNamespace(selected_personas=[clinician, patient],
                           patient_persona_id=None)
    assert ehr_seed.patient_persona_id(sess) == patient


def test_explicit_patient_pick_still_wins():
    patient = _find_by_rolegroup("Patient")
    clinician = _find_by_rolegroup("Clinician")
    sess = SimpleNamespace(selected_personas=[clinician], patient_persona_id=patient)
    assert ehr_seed.patient_persona_id(sess) == patient


def test_chart_seeds_from_the_patient_not_the_first_clinician():
    patient = _find_by_rolegroup("Patient")
    clinician = _find_by_rolegroup("Clinician")
    sess = SimpleNamespace(selected_personas=[clinician, patient],
                           patient_persona_id=None, selected_modules=[],
                           scenario_text="")
    seed = ehr_seed.seed_from_session(sess, ehr_id="cyrus")
    assert seed is not None
    patient_name = library.get_persona(patient)["name"]
    clinician_name = library.get_persona(clinician)["name"]
    assert seed["persona_id"] == patient
    assert seed["name"] == patient_name and seed["name"] != clinician_name


def test_legacy_fallback_when_no_patient_present():
    # All-clinician selection (degenerate) → fall back to the first entry, never None.
    clinician = _find_by_rolegroup("Clinician")
    sess = SimpleNamespace(selected_personas=[clinician], patient_persona_id=None)
    assert ehr_seed.patient_persona_id(sess) == clinician
