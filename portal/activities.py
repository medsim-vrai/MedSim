"""V7 — Activity catalog (M11).

An **Activity** is a persistent, instructor-curated case template
that seeds an Encounter when picked from the wizard's room-mode
editor (M12). It bundles a primary patient persona, a default set of
NCLEX modules, a free-form scenario text the wizard pre-fills into
Step 3, a default chart mode, and optionally an answer key.

Built-in Activities are seeded on first DB access via
``seed_builtins()`` — idempotent, safe to call on every server
start. The seven samples mirror ``portal/data/sample_scenarios.json``
exactly so an Activity-picked encounter and a wizard-template-picked
encounter produce identical seed material. The eighth built-in
(``builtin_msurg_resp_failure``) extends coverage to acute
respiratory failure / pneumonia — a curriculum gap in the samples.

Cross-references:
  - Schema: ``ehr_db.SCHEMA_MIGRATIONS`` migration 4 (M1).
  - CRUD:   ``ehr_db.{create_activity, get_activity, list_activities,
            update_activity, delete_activity}``.
  - Design rationale: ``research/p6_v7_architecture.md`` §4.12.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import ehr_db


@dataclass
class Activity:
    """In-memory shape of an Activity row. Mirrors the DB schema 1:1.

    Most callers use the dict shape returned by ``ehr_db.get_activity``
    / ``ehr_db.list_activities``; this dataclass is a typed helper for
    constructing Activities programmatically (e.g. the built-in seed
    list below)."""
    activity_id:        str
    label:              str
    seed_persona_id:    str | None = None
    seed_modules:       list[str] = field(default_factory=list)
    scenario_text:      str = ""
    default_chart_mode: str = "shared"
    answer_key:         dict[str, Any] | None = None
    is_builtin:         bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id":        self.activity_id,
            "label":              self.label,
            "seed_persona_id":    self.seed_persona_id,
            "seed_modules":       list(self.seed_modules),
            "scenario_text":      self.scenario_text,
            "default_chart_mode": self.default_chart_mode,
            "answer_key":         dict(self.answer_key) if self.answer_key else None,
            "is_builtin":         self.is_builtin,
        }


# ── Built-in catalog ─────────────────────────────────────────────────
#
# The first 7 mirror portal/data/sample_scenarios.json. The 8th
# extends coverage to acute respiratory failure. Each entry's
# ``seed_persona_id`` is the primary patient — typically the first
# patient in the v6 sample's personas[] list.

BUILTIN_ACTIVITIES: list[Activity] = [
    Activity(
        activity_id="builtin_ed_sepsis_delirium",
        label="ED · Sepsis with hyperactive delirium",
        seed_persona_id="P-014",  # adult patient in the sample's roster
        seed_modules=["M32", "M08", "M02"],
        scenario_text=(
            "78-year-old male POD #2 from sigmoid resection. Vitals "
            "trending — last set: T 38.7°C, HR 122, BP 84/52, RR 26, "
            "SpO2 91% on 2 L NC. Lactate 4.2 just back from the lab. "
            "Patient now hyperactive — picking at his IV, paranoid about "
            "staff entering the room. Wife at bedside crying. Charge "
            "nurse paged for assistance. Pre-existing COPD."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_msurg_postop_pain",
        label="Med-surg · Postop pain — RN/LPN delegation",
        seed_persona_id="P-012",
        seed_modules=["M08", "M06", "M02"],
        scenario_text=(
            "62-year-old female POD #1 from laparoscopic cholecystectomy. "
            "Reports incisional pain 7/10. Vitals: T 37.2, HR 96, BP "
            "138/82, RR 18, SpO2 98% on room air. Acetaminophen scheduled, "
            "PRN oxycodone ordered. LPN reports patient asking for pain "
            "medicine — wants to know what to give. Practice RN/LPN scope "
            "delegation and closed-loop communication."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_mh_passive_si",
        label="Mental health · Goals-of-care + passive SI",
        seed_persona_id="P-019",
        seed_modules=["M39", "M02"],
        scenario_text=(
            "54-year-old female admitted for medical workup after a "
            "primary care visit during which she stated 'I wish I "
            "wouldn't wake up.' Denies plan. History of major depression. "
            "Family at bedside, supportive but tearful. Discussion of "
            "goals of care, safety planning, social work consult. High-"
            "risk persona — instructor in the loop."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_substance_etoh_withdrawal",
        label="Substance · Alcohol withdrawal (CIWA-Ar)",
        seed_persona_id="P-016",
        seed_modules=["M06", "M02", "M39"],
        scenario_text=(
            "52-year-old man admitted with acute pancreatitis. Reports "
            "last alcoholic drink 36 hours ago — daily heavy use prior. "
            "Now tremulous, diaphoretic, anxious. Reports seeing 'spiders "
            "on the wall.' Last CIWA-Ar score: 14. Lorazepam 2 mg IV q1h "
            "PRN ordered but pharmacy delayed delivery; smart pump "
            "alarming on dose-range check. Charge nurse paged, "
            "pharmacist available."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_peds_febrile_child",
        label="Peds · Febrile child, anxious parent",
        seed_persona_id="P-003",
        seed_modules=["M06", "M07", "M03", "M02"],
        scenario_text=(
            "4-year-old female presenting with 39.1°C fever, decreased "
            "PO intake, lethargy. HR 142, RR 32, SpO2 96% on room air. "
            "Parent visibly anxious — concerned about meningitis. "
            "Working dx: viral URI vs. early bacterial illness. Practice "
            "weight-based dosing, family-centered communication, sepsis "
            "screening."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_geri_goals_of_care",
        label="Geri · Goals-of-care with grieving family",
        seed_persona_id="P-013",
        seed_modules=["M42", "M02"],
        scenario_text=(
            "82-year-old female with advanced dementia, recurrent "
            "aspiration pneumonia. Admitted from skilled nursing facility. "
            "Family meeting scheduled — adult children disagree on goals "
            "of care (one wants full code, one wants comfort care). "
            "Practice POLST discussion, palliative consult, family-systems "
            "communication."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_msurg_dka",
        label="Med-surg · DKA management",
        seed_persona_id="P-005",
        seed_modules=["M22", "M06", "M02"],
        scenario_text=(
            "23-year-old male with T1DM presenting in DKA. Glucose 524, "
            "anion gap 22, pH 7.18, bicarb 12, ketones present. Fluids "
            "running, insulin drip per protocol. Pump alarming on insulin "
            "infusion rate — needs verification against MAR. Practice "
            "fluid resuscitation, electrolyte replacement, insulin drip "
            "titration, transition to subcutaneous."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
    Activity(
        activity_id="builtin_msurg_resp_failure",
        label="Med-surg · Acute respiratory failure",
        seed_persona_id="P-006",
        seed_modules=["M07", "M06", "M02"],
        scenario_text=(
            "68-year-old male admitted with community-acquired pneumonia "
            "now in acute hypoxemic respiratory failure. SpO2 86% on "
            "6 L NC, RR 32, accessory muscle use, mild confusion. "
            "Respiratory therapy at bedside, BiPAP being set up. ABG "
            "pending. Considering ICU transfer. Practice oxygen escalation, "
            "ABG interpretation, criteria for higher level of care, "
            "closed-loop with RT and provider."
        ),
        default_chart_mode="shared",
        is_builtin=True,
    ),
]


# ── Public API ───────────────────────────────────────────────────────

def seed_builtins() -> int:
    """Idempotently ensure every Activity in ``BUILTIN_ACTIVITIES`` is
    present in the DB. Returns the number of rows inserted or updated.

    Built-in activities can be edited by an instructor through the
    M12 routes — those edits persist. ``seed_builtins`` does NOT
    overwrite an existing row's instructor-edited fields; it only
    inserts rows missing from the DB. To force-refresh the catalog
    to baseline, the operator can delete the built-in row (M12 will
    surface a "Reset to defaults" affordance — out of scope for M11).
    """
    written = 0
    for a in BUILTIN_ACTIVITIES:
        if ehr_db.get_activity(a.activity_id) is not None:
            continue
        ehr_db.create_activity(
            activity_id=a.activity_id,
            label=a.label,
            seed_persona_id=a.seed_persona_id,
            seed_modules=a.seed_modules,
            scenario_text=a.scenario_text,
            default_chart_mode=a.default_chart_mode,
            answer_key=a.answer_key,
            is_builtin=True,
        )
        written += 1
    return written


def list_all() -> list[dict[str, Any]]:
    """Convenience pass-through to ``ehr_db.list_activities()`` so
    callers can import only ``portal.activities``."""
    return ehr_db.list_activities()


def get(activity_id: str) -> dict[str, Any] | None:
    return ehr_db.get_activity(activity_id)


def to_encounter_entry(activity_id: str) -> dict[str, Any] | None:
    """Translate an Activity into the wizard's encounter-row shape
    (the same dict the M4 ``POST /api/room/start`` route accepts).
    Returns None if the activity id is unknown. M12's wizard hook
    consumes this."""
    a = ehr_db.get_activity(activity_id)
    if a is None:
        return None
    return {
        "scenario_name":      a["label"],
        "scenario_notes":     "",
        "scenario_text":      a["scenario_text"],
        "modules":            list(a["seed_modules"]),
        "personas":           [a["seed_persona_id"]] if a["seed_persona_id"] else [],
        "persona_id":         a["seed_persona_id"],
        "patient_persona_id": a["seed_persona_id"],
        "chart_mode":         a["default_chart_mode"],
        "activity_id":        a["activity_id"],
    }
