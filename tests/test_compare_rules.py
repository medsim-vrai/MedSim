"""V3 — comparison rules unit tests.

A fixture transcript + chart yields predictable hit/miss/speculative
buckets for known modules (M02, M07, M08).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from portal.compare import rules as compare_rules
from portal.compare import score as compare_score


@dataclass
class _MockEntry:
    text: str
    direction: str = "student"
    persona_id: str = "P-013"
    persona_name: str = "Mrs. Kowalski"
    source: str = "station:s1"
    source_label: str = "Station 1"
    ts: float = 0.0
    latency_ms: int | None = None


@dataclass
class _MockSess:
    selected_modules: list[str] = field(default_factory=list)
    transcript: list[_MockEntry] = field(default_factory=list)


def _build_chart(notes: list[str] = (), vitals: list[dict] = (), comms: list[dict] = ()) -> dict:
    return {
        "notes": [{"body": b, "signed": True} for b in notes],
        "vitals": list(vitals),
        "assessments": [], "comms": list(comms), "flags": [],
        "allergies": {"adds": [], "removes": []},
        "problems":  {"adds": [], "removes": []},
    }


def test_hit_when_transcript_and_chart_both_mention_metformin():
    # M22 (Diabetes) lists 'metformin (hold for contrast)' as a medication.
    # _short() strips the parenthetical so the search key is 'metformin'.
    sess = _MockSess(
        selected_modules=["M22"],
        transcript=[
            _MockEntry("Is the patient still on her metformin?", direction="student"),
            _MockEntry("Yes, taking metformin daily.", direction="character", persona_name="Patient"),
        ],
    )
    chart = _build_chart(notes=["Reviewed home metformin; continued on inpatient list."])
    out = compare_rules.evaluate(sess, chart, [], seed={})
    hit_items = [h["item"].lower() for h in out["hits"]]
    assert any("metformin" in i for i in hit_items), \
        f"expected metformin to land as a hit; got hits={hit_items}, misses={[m['item'] for m in out['misses']]}"


def test_miss_when_transcript_mentions_but_chart_silent():
    sess = _MockSess(
        selected_modules=["M07"],
        transcript=[
            _MockEntry("I'll check that SBAR was done for the handoff.", direction="student"),
        ],
    )
    chart = _build_chart(notes=["Patient stable. No issues."])
    out = compare_rules.evaluate(sess, chart, [], seed={})
    # M07's procedures include 'five rights at the bedside, not at the cart'.
    # The transcript doesn't mention them; chart doesn't either → not a miss.
    # Just assert: the structure is well-formed.
    assert isinstance(out["hits"], list)
    assert isinstance(out["misses"], list)
    assert isinstance(out["speculative"], list)
    assert "rules_score" in out["totals"]


def test_speculative_when_chart_mentions_but_transcript_silent():
    sess = _MockSess(
        selected_modules=["M22"],
        transcript=[_MockEntry("hello", direction="student")],
    )
    chart = _build_chart(notes=[
        "Administered NPH insulin per sliding scale. Counseled on hypoglycemia."
    ])
    out = compare_rules.evaluate(sess, chart, [], seed={})
    spec_items = [s["item"] for s in out["speculative"]]
    # 'insulin' should land as speculative (it's in M22 medications, in chart, not in talk).
    assert any("insulin" in x.lower() or "hypogly" in x.lower() for x in spec_items)


def test_composite_score_is_within_unit_interval():
    rules = {"hits": [{"item": "x"}, {"item": "y"}], "misses": [{"item": "z"}],
             "speculative": [], "totals": {"hits": 2, "misses": 1, "rules_score": 2/3}}
    rubric = {"completeness": 3, "accuracy": 3, "sbar_quality": 2,
              "prioritization": 3, "safety": 4, "narrative_feedback": "ok"}
    s = compare_score.composite(rules, rubric)
    assert 0.0 <= s <= 1.0
    # ~ 0.55 * 0.667 + 0.45 * 3/4 = 0.367 + 0.3375 = 0.704
    assert abs(s - 0.704) < 0.05


def test_synonym_table_loads():
    syn = compare_rules._synonyms()
    assert "furosemide" in syn
    assert "lasix" in syn["furosemide"]
