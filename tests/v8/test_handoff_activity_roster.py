"""2026-06-13 — multi-patient character-roster parity with single-patient.

The room wizard auto-checks a bed's full character roster from the SAME-NAMED
sample scenario (the client matches activity.label == sample.name and ticks
sample.personas[]). These tests pin that contract at the data level so a rename
can't silently break the linkage (the DOM wiring itself has no JS harness)."""
from __future__ import annotations

import json
from pathlib import Path

import portal
from portal import activities, library

SAMPLES = {s["name"]: s for s in json.loads(
    (Path(portal.__file__).parent / "data" / "sample_scenarios.json").read_text()
)["samples"]}


def test_hayes_activity_pulls_the_full_supporting_roster():
    """Mr. Hayes (sepsis/delirium) must bring his doctor, charge nurse, RT and
    wife — the exact roster single-patient gets — not just the patient."""
    act = next(a for a in activities.BUILTIN_ACTIVITIES
               if a.seed_persona_id == "P-014")
    sample = SAMPLES.get(act.label)
    assert sample is not None, f"no sample named {act.label!r} for the Hayes activity"
    roster = sample["personas"]
    assert "P-014" in roster                       # the patient himself
    assert len(roster) >= 4                         # + supporting cast
    # The roster carries a clinician (doctor) and non-patient role-players.
    groups = {library.get_persona(p).get("roleGroup") for p in roster}
    assert "Patient" in groups and (groups - {"Patient"}), \
        "roster should mix the patient with clinicians/family"


def test_every_sample_backed_activity_roster_contains_its_patient():
    """For each built-in activity whose label matches a sample, that sample's
    roster includes the activity's seed patient — so auto-checking the roster
    always includes the patient (never drops them)."""
    linked = 0
    for a in activities.BUILTIN_ACTIVITIES:
        sample = SAMPLES.get(a.label)
        if sample is None:
            continue                                # e.g. the resp-failure activity (no sample)
        linked += 1
        assert a.seed_persona_id in sample["personas"], \
            f"{a.activity_id}: patient {a.seed_persona_id} not in sample roster"
    assert linked >= 6, "expected most built-in activities to map to a sample"
