"""ChartSeed builder — persona + selected modules → neutral chart-seed dict.

The output is intentionally EHR-agnostic. Per-EHR adapters
(`portal/ehr/{ehr_id}/adapter.py::install`) translate the neutral seed
into the EHR's native row shapes. The seed is frozen at session start
so the comparison engine can compute 'additions made by the student'
by diffing the final chart against the seed.

Data hygiene rules (Blueprint §5):
- synthetic only — names + DOBs + MRNs are generated, never copied from
  the operator's input
- never returns identifiers that look like real PHI

Module-driven content (Blueprint §5, Stage A):
- problem list seeded from `modules[].conditions`
- home meds seeded from `modules[].medications` (selecting a sensible
  subset for the patient's role/age)
- allergies pulled from a small persona-keyed table
- vitals_baseline + labs_recent pulled from a small acuity-keyed table
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

from . import library


# ──────────────────────────────────────────────────────────────────────
# V6 — clinical catalog loading (one-time, module-level)
# ──────────────────────────────────────────────────────────────────────
_DATA = Path(__file__).resolve().parent / "data"


def _load_catalog(path_name: str) -> dict[str, Any]:
    try:
        return json.loads((_DATA / path_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


CLINICAL_RANGES     = _load_catalog("clinical_ranges.json")
DRUG_DOSES          = _load_catalog("drug_doses.json")
IV_FLUID_CATALOG    = _load_catalog("iv_fluid_catalog.json")
TUBE_FEED_CATALOG   = _load_catalog("tube_feed_catalog.json")
TREATMENT_TIMELINES = _load_catalog("treatment_timelines.json")

# V6.1 — high-alert drug classes get an `high_alert: true` flag on the
# MAR row. Visual cue for trainees (mirrors ISMP high-alert med list).
_HIGH_ALERT_CLASSES = {
    "opioid", "anticoagulant", "DOAC", "insulin-long", "insulin-rapid",
    "insulin-regular", "vasopressor", "inotrope", "electrolyte",
    "fibrinolytic", "antifibrinolytic", "alpha-2 agonist",
}


# Keyword → condition slug. The seeder scans persona.alteredState, module
# titles, and scenario_text against this map (case-insensitive). First
# match wins; falls back to 'stable_baseline'.
_CONDITION_KEYWORDS: list[tuple[str, str]] = [
    ("septic shock",      "septic_shock"),
    ("sepsis",            "sepsis"),
    ("chf",               "chf_exacerbation"),
    ("heart failure",     "chf_exacerbation"),
    ("stemi",             "mi_stemi"),
    ("acs",               "mi_stemi"),
    ("mi ",               "mi_stemi"),
    ("ischemic stroke",   "stroke_ischemic"),
    ("cva",               "stroke_ischemic"),
    ("gi bleed",          "gi_bleed_upper"),
    ("upper gi",          "gi_bleed_upper"),
    ("hematemesis",       "gi_bleed_upper"),
    ("pneumonia",         "pneumonia"),
    ("pulmonary embolism","pe_pulmonary_embolism"),
    ("pe ",               "pe_pulmonary_embolism"),
    ("copd",              "copd_exacerbation"),
    ("asthma",            "asthma_exacerbation"),
    ("dka",               "dka"),
    ("ketoacidosis",      "dka"),
    ("hyperkalemia",      "hyperkalemia"),
    ("hyperkalemic",      "hyperkalemia"),
    ("aki",               "aki"),
    ("acute kidney",      "aki"),
    ("anaphylaxis",       "anaphylaxis"),
    ("alcohol-withdrawal","alcohol_withdrawal"),
    ("alcohol withdrawal","alcohol_withdrawal"),
    ("ciwa",              "alcohol_withdrawal"),
    ("opioid",            "opioid_overdose"),
    ("overdose",          "opioid_overdose"),
    ("stimulant",         "stimulant_intoxication"),
    ("cocaine",           "stimulant_intoxication"),
    ("methamphetamine",   "stimulant_intoxication"),
    ("delirium",          "delirium"),
    ("post-op",           "post_op_stable"),
    ("post op",           "post_op_stable"),
    ("hypoglycemia",      "hypoglycemia"),
    ("hhs",               "hyperglycemia_hhs"),
    ("hyperosmolar",      "hyperglycemia_hhs"),
    ("trauma",            "trauma_blunt"),
    ("postpartum",        "ob_postpartum_hemorrhage"),
    ("pediatric dehydration", "peds_dehydration"),
    ("dehydrat",          "peds_dehydration"),
    ("psychosis",         "psychosis_acute"),
]


def detect_condition(persona: dict[str, Any],
                      modules: list[dict[str, Any]],
                      scenario_text: str) -> str:
    """Pick the most specific PRIMARY condition slug to drive vitals
    and labs. Multi-system patients are common (e.g., septic shock +
    delirium + COPD baseline) — secondary diagnoses surface via
    detect_overlays(). The PRIMARY is whichever condition's vitals best
    fit the picture, so it gets to drive the randomization ranges.

    Priority: persona.condition (explicit) → alteredState → module IDs
    and titles → scenario_text. Falls back to 'stable_baseline'.
    """
    # 1. Explicit field always wins.
    explicit = (persona.get("condition") or "").strip().lower()
    if explicit in CLINICAL_RANGES:
        return explicit

    txt = (scenario_text or "").lower()
    hay = " ".join(
        (m.get("id") or "") + " " + (m.get("title") or "") + " " +
        " ".join(m.get("conditions") or [])
        for m in modules
    ).lower()
    combined = hay + " || " + txt

    # 2. Numeric red flags in the scenario beat any persona label. A
    # patient described as hypotensive + lactate-elevated IS in shock,
    # regardless of whether the persona's alteredState says 'delirium'
    # (which becomes an overlay instead).
    if _scenario_indicates_shock(txt) and "septic_shock" in CLINICAL_RANGES:
        return "septic_shock"

    # 3. Scenario / module keyword scan next — gives the operator's
    # explicit description priority over the persona's resting label.
    for kw, slug in _CONDITION_KEYWORDS:
        if kw in combined and slug in CLINICAL_RANGES:
            return slug

    # 4. Fallback: persona.alteredState as the rest-state diagnosis.
    altered = (persona.get("alteredState") or "").strip().lower()
    for kw, slug in _CONDITION_KEYWORDS:
        if kw in altered and slug in CLINICAL_RANGES:
            return slug

    return "stable_baseline"


def _scenario_indicates_shock(txt: str) -> bool:
    """Numeric red-flag scan: hypotension + elevated lactate or HR > 120
    with low BP. Beats keyword-only detection when the scenario gives
    explicit vitals instead of naming the syndrome."""
    sys_m = re.search(r"bp\s*[:= ]?\s*(\d{2,3})\s*/\s*\d{2,3}", txt)
    lac_m = re.search(r"lactate\s+(\d+(?:\.\d+)?)", txt)
    bp_low = sys_m and int(sys_m.group(1)) < 90
    lac_high = lac_m and float(lac_m.group(1)) >= 2.5
    fever = ("fever" in txt or "febrile" in txt or
             re.search(r"t\s*[:= ]?\s*3[89](?:\.\d)?", txt) is not None)
    return bool(bp_low and (lac_high or fever))


# Overlay conditions: not the primary driver of vitals, but the patient
# carries the picture and meds should reflect it.
_OVERLAY_KEYWORDS: list[tuple[str, str]] = [
    ("hyperactive",                   "delirium"),
    ("picking at",                    "delirium"),
    ("paranoid",                      "delirium"),
    ("confused",                      "delirium"),
    ("agitated",                      "delirium"),
    ("delirium",                      "delirium"),
    ("post-op",                       "post_op_stable"),
    ("post op",                       "post_op_stable"),
    ("pod #",                         "post_op_stable"),
    ("pod#",                          "post_op_stable"),
    ("post-operative",                "post_op_stable"),
    ("postoperative",                 "post_op_stable"),
    ("copd",                          "copd_exacerbation"),
    ("emphysema",                     "copd_exacerbation"),
    ("asthma",                        "asthma_exacerbation"),
    ("alcohol withdrawal",            "alcohol_withdrawal"),
    ("ciwa",                          "alcohol_withdrawal"),
]


def detect_overlays(persona: dict[str, Any],
                     modules: list[dict[str, Any]],
                     scenario_text: str,
                     primary: str) -> list[str]:
    """Detect secondary diagnoses the patient ALSO has. Used to widen
    the MAR — overlays contribute their standard-of-care meds in
    addition to the primary's. Does NOT alter vital ranges; the primary
    still drives those.
    """
    hay = (" ".join((m.get("id") or "") + " " + (m.get("title") or "") + " " +
                     " ".join(m.get("conditions") or []) for m in modules) +
           " " + (scenario_text or "")).lower()
    altered = (persona.get("alteredState") or "").lower()
    found: list[str] = []
    seen: set[str] = {primary}
    for kw, slug in _OVERLAY_KEYWORDS:
        if slug in seen:
            continue
        if (kw in hay or kw in altered) and slug in CLINICAL_RANGES:
            found.append(slug)
            seen.add(slug)
    return found


# V6.1 — parse "admitted N hours ago" / "POD #N" / "presented to ED N h
# ago" from scenario text. Returns a UNIX epoch float for admit_time.
# Falls back to now - 2h for vague cases (acute presentation default).
def detect_admit_time(scenario_text: str, encounter: dict[str, Any]) -> float:
    txt = (scenario_text or "").lower()
    now = time.time()
    # Post-op day N → admitted N×24h ago.
    pod_m = re.search(r"\bpod\s*#?\s*(\d+)\b", txt)
    if pod_m:
        return now - int(pod_m.group(1)) * 24 * 3600
    # "admitted N h/hr/hours ago" or "presented N h ago"
    h_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\s*ago", txt)
    if h_m:
        return now - float(h_m.group(1)) * 3600
    # "for the past N days" → admitted N days ago (chronic presentation)
    d_m = re.search(r"(?:past|last|previous)\s+(\d+)\s+days?", txt)
    if d_m:
        return now - int(d_m.group(1)) * 24 * 3600
    # Encounter LOS: "Day N" → admitted (N-1)*24h ago (Day 1 = admit today)
    los = (encounter.get("los") or "").lower()
    los_m = re.search(r"day\s+(\d+)", los)
    if los_m:
        day = int(los_m.group(1))
        return now - max(0, day - 1) * 24 * 3600
    # Default: 2 hours ago (acute, but enough history to have given a few doses)
    return now - 2 * 3600


# Oxygen pick — picks a delivery + flow per scenario fingerprint, then
# stamps that drug name onto the MAR. Conservative algorithm: prefer
# lowest flow that fits SpO2 target, and bias to NC over mask for COPD
# (avoid hyperoxia → hypercapnia in CO2 retainers).
def _oxygen_pick(condition: str, overlays: list[str],
                  scenario_text: str) -> str | None:
    txt = (scenario_text or "").lower()
    spo2_m = re.search(r"spo2\s*[:= ]?\s*(\d{2,3})", txt)
    flow_m = re.search(r"(\d+(?:\.\d+)?)\s*l\s*(?:per\s*min|/min)?\s*(?:nc|nasal)", txt)
    nrb = "nrb" in txt or "non-rebreather" in txt
    hfnc = "hfnc" in txt or "high-flow" in txt or "high flow nasal" in txt
    is_copd = "copd_exacerbation" in overlays or "copd" in txt or "emphysema" in txt

    # Explicit flow already in scenario text — honor it.
    if flow_m:
        flow = float(flow_m.group(1))
        if flow <= 2.5: return "Oxygen 2 L NC"
        if flow <= 4.5: return "Oxygen 4 L NC"
        return "Oxygen 6 L NC"
    if hfnc: return "Oxygen HFNC"
    if nrb:  return "Oxygen NRB"
    if condition == "anaphylaxis": return "Oxygen NRB"
    spo2 = int(spo2_m.group(1)) if spo2_m else None
    needs_o2 = (
        spo2 is not None and spo2 < 95
        or condition in ("septic_shock", "pneumonia", "copd_exacerbation",
                          "asthma_exacerbation", "pe_pulmonary_embolism", "chf_exacerbation")
    )
    if not needs_o2:
        return None
    # Conservative default — COPD gets 2 L NC, others 4 L NC.
    return "Oxygen 2 L NC" if is_copd else "Oxygen 4 L NC"


class ChartSeed(TypedDict, total=False):
    mrn: str
    fin: str
    name: str
    persona_id: str        # the 24-library persona this chart represents
    persona_label: str     # the persona's original library name (traceability)
    chief_complaint: str   # presenting concern, surfaced in the patient banner
    dob: str
    sex: str
    pronouns: str
    code_status: str
    allergies: list[dict[str, str]]
    problem_list: list[dict[str, str]]
    medications: list[dict[str, Any]]
    immunizations: list[dict[str, str]]
    social_history: dict[str, Any]
    family_history: list[dict[str, str]]
    surgical_history: list[dict[str, str]]
    vitals_baseline: list[dict[str, str]]
    labs_recent: list[dict[str, Any]]
    notes_recent: list[dict[str, Any]]
    care_team: list[dict[str, str]]
    encounter: dict[str, Any]
    altered_state: str | None
    safety_class: str
    module_anchors: list[str]
    weight: str
    height: str
    bsa: str
    insurance: str
    # V6 additions
    condition: str
    iv_fluids: list[dict[str, Any]]
    tube_feeds: list[dict[str, Any]]
    seed_report: dict[str, Any]


# ──────────────────────────────────────────────────────────────────────
# Public
# ──────────────────────────────────────────────────────────────────────

def seed_from_persona(
    persona: dict[str, Any],
    *,
    modules: list[dict[str, Any]] | None = None,
    scenario_text: str = "",
    ehr_id: str = "helix",
) -> ChartSeed:
    """Build a ChartSeed from a 24-persona dict + selected modules.

    The chart's patient identity IS the scenario's primary persona — its
    name, age, sex, altered state. Scenario detail (the free-form
    scenario_text) and the selected curriculum modules flow into the
    admission note, the chief complaint, the encounter reason, and the
    problem list, so the student opens a chart that matches the scenario
    they are running.
    """
    modules = modules or []
    rng = _deterministic_rng(persona.get("id", ""))
    name = _patient_name(persona, rng)
    dob = _dob_from_age_range(persona.get("ageRange", "40"), rng)
    sex = persona.get("sex") or _sex_from_voice(persona)
    safety = persona.get("safetyClass", "baseline")
    altered = persona.get("alteredState")
    # V6 — pick the PRIMARY condition (drives vitals/labs) plus any
    # secondary diagnoses that contribute meds. Real patients are
    # multi-system; the seeder reflects that.
    condition = detect_condition(persona, modules, scenario_text)
    overlays  = detect_overlays(persona, modules, scenario_text, condition)
    oxygen_drug = _oxygen_pick(condition, overlays, scenario_text)

    code_status = _code_status(persona, modules, altered)
    allergies = _allergies_for(persona, rng)
    problems = _problems_from_modules(persona, modules, scenario_text)
    encounter = _encounter_meta(persona, modules, scenario_text, ehr_id)
    # V6.1 — anchor MAR + admin history to scenario admission time.
    admit_time = detect_admit_time(scenario_text, encounter)
    encounter["admit_time"] = _ts_to_iso(admit_time)
    weight_str = _weight_for(persona, rng)
    weight_kg = _weight_kg_from(weight_str)
    care_team = _care_team(persona, encounter, rng)
    meds = _build_mar(persona, modules, condition, overlays, oxygen_drug,
                       weight_kg, admit_time, care_team, rng)
    vitals = _baseline_vitals(persona, condition, altered, encounter, rng)
    labs = _baseline_labs(persona, condition, modules, rng)
    iv_fluids = _build_iv_fluids(persona, condition, weight_kg, rng)
    tube_feeds = _build_tube_feeds(persona, condition, rng)
    # care_team already computed above for MAR admin-history attribution
    chief = _chief_complaint(persona, modules, scenario_text)

    chart_seed = ChartSeed(
        mrn=_mint_mrn(ehr_id, persona.get("id", "")),
        fin=_mint_fin(persona.get("id", "")) if ehr_id == "cyrus" else None,  # type: ignore[typeddict-item]
        name=name,
        persona_id=persona.get("id", ""),
        persona_label=persona.get("name", ""),
        chief_complaint=chief,
        dob=dob,
        sex=sex,
        pronouns=persona.get("pronouns") or _pronouns_from_sex(sex),
        code_status=code_status,
        allergies=allergies,
        problem_list=problems,
        medications=meds,
        immunizations=_default_imms(persona),
        social_history=_social_for(persona),
        family_history=_family_for(persona, modules),
        surgical_history=_surgical_for(persona, modules),
        vitals_baseline=vitals,
        labs_recent=labs,
        notes_recent=_baseline_notes(persona, name, chief, scenario_text,
                                      encounter, modules),
        care_team=care_team,
        encounter=encounter,
        altered_state=altered,
        safety_class=safety,
        module_anchors=[m.get("id", "") for m in modules],
        weight=weight_str,
        height=_height_for(persona, rng),
        bsa=_bsa_for(persona, rng),
        insurance=_insurance_for(persona),
        condition=condition,
        iv_fluids=iv_fluids,
        tube_feeds=tube_feeds,
    )
    # V6 — record secondary diagnoses so the validator + UI can surface them.
    chart_seed["overlays"] = overlays  # type: ignore[typeddict-item]
    # Validate + auto-correct. Surfaces warnings on the operator's seed
    # report card; never blocks scenario start.
    chart_seed["seed_report"] = validate_chart_seed(chart_seed)
    return chart_seed


# ──────────────────────────────────────────────────────────────────────
# Helpers — all deterministic given persona.id so reseeds are stable
# ──────────────────────────────────────────────────────────────────────

def _deterministic_rng(seed_str: str) -> random.Random:
    h = hashlib.sha256(seed_str.encode("utf-8")).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _mint_mrn(ehr_id: str, persona_id: str) -> str:
    digits = "".join(c for c in hashlib.sha1(persona_id.encode()).hexdigest() if c.isdigit())[:8]
    digits = (digits + "00000000")[:8]
    return {"helix": f"HLX-{digits}", "cyrus": f"CY-{digits}", "meridian": f"MER-2026-{digits[:5]}"}.get(
        ehr_id, f"MRN-{digits}"
    )


def _mint_fin(persona_id: str) -> str:
    digits = "".join(c for c in hashlib.sha1(("FIN" + persona_id).encode()).hexdigest() if c.isdigit())[:7]
    return f"FIN-2026-{(digits + '0000000')[:7]}"


_FIRST_F = ["Marisol","Helena","Imani","Eleanor","Aaliyah","Penelope","Yuki","Anastasia",
            "Soraya","Linnea","Beatriz","Marguerite","Ngozi","Adaeze","Naomi","Tamsin"]
_FIRST_M = ["Daniyar","Tobias","Caleb","Bo","Mateo","Soren","Hideki","Esteban",
            "Reuben","Anders","Tarun","Cyrus","Aurelio","Konstantin","Olufemi","Jamir"]
_LAST    = ["Fontaine-Reyes","Tashkenbayev","Whitcombe","Wojciechowska","Eklund-Marsh",
            "Robidoux","Hightower","Whitford-Bayle","Acheampong","Olamide","Petrov-Lin",
            "Borisov","Lefebvre","Vasquez-Cruz","Almasri","Ng-Singh","Kwiatkowski","Adeyemi"]


_DESCRIPTOR_WORDS = {
    "spouse", "child", "adult", "visitor", "family", "psychosis", "patient",
    "pt", "pregnant", "lep", "spanish", "hostile", "anxious", "grieving",
    "acute", "first-episode", "withdrawal", "tox", "delirium", "synth",
}
_TITLES = {"Mr", "Mrs", "Ms", "Mx", "Dr"}


def _patient_name(persona: dict[str, Any], rng: random.Random) -> str:
    """Resolve the EHR patient's name FROM the scenario persona.

    The chart patient is the scenario's primary persona — V2-V4 wrongly
    invented a random name here, so the records never matched the
    scenario. Rules:
      - "Mr. Bennett" / "Mrs. Kowalski"  → kept verbatim (proper names)
      - "Adi (age 7)" / "Pregnant Pt Jia" → given name kept, deterministic
        surname added → "Adi Whitcombe"
      - "Acute Psychosis" / "Anxious Spouse" → pure descriptors, no name;
        a deterministic synthetic name is generated (and persona_label
        still records the original so the link is never lost)
    `rng` is seeded on persona.id, so a given persona always maps to the
    same name across reseeds.
    """
    raw = (persona.get("name") or "").strip()
    clean = re.sub(r"\s*\([^)]*\)", "", raw).strip()      # drop "(age 7)"
    tokens = clean.split()

    # Title + surname → keep verbatim.
    if tokens and tokens[0].rstrip(".") in _TITLES and len(tokens) >= 2:
        return clean

    # Tokens that look like real name parts (not role descriptors).
    name_tokens = [
        t for t in tokens
        if t.lower().strip(".—-") not in _DESCRIPTOR_WORDS
        and re.match(r"^[A-Za-z][A-Za-z'\-]+$", t)
    ]
    if len(name_tokens) >= 2:
        return " ".join(name_tokens)
    if len(name_tokens) == 1:
        # A single given name (Adi, Jia) — add a deterministic surname.
        return f"{name_tokens[0]} {rng.choice(_LAST)}"

    # Pure descriptor persona — synthesize a deterministic full name.
    sex = persona.get("sex") or _sex_from_voice(persona)
    first = rng.choice(_FIRST_F) if sex == "F" else rng.choice(_FIRST_M)
    return f"{first} {rng.choice(_LAST)}"


def _dob_from_age_range(age_range: str, rng: random.Random) -> str:
    if not age_range:
        age = 40
    elif "-" in age_range:
        lo, hi = age_range.split("-", 1)
        try:
            age = rng.randint(int(lo), int(hi))
        except ValueError:
            age = 40
    else:
        try:
            age = int(re.sub(r"\D", "", age_range) or "40")
        except ValueError:
            age = 40
    today = date.today()
    dob = today.replace(year=today.year - age) - timedelta(days=rng.randint(0, 364))
    return dob.isoformat()


def _sex_from_voice(persona: dict[str, Any]) -> str:
    vp = (persona.get("voiceProfile") or "").lower()
    if "female" in vp or "moira" in vp or "samantha" in vp:
        return "F"
    if "male" in vp:
        return "M"
    return "U"


def _pronouns_from_sex(sex: str) -> str:
    return {"F": "she/her", "M": "he/him"}.get(sex, "they/them")


def _code_status(persona: dict[str, Any], modules: list[dict[str, Any]],
                  altered: str | None) -> str:
    age_str = persona.get("ageRange", "40")
    age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    mods = {m.get("id") for m in modules}
    if "M42" in mods:  # End-of-life
        return "DNR/DNI"
    if age >= 75 and persona.get("roleGroup") == "Patient":
        return "DNR"
    if altered in {"psychosis", "depression-passive-si"}:
        return "Full Code"
    return "Full Code"


_PERSONA_ALLERGIES = {
    "P-013": [{"substance": "Penicillin", "reaction": "hives", "severity": "moderate"}],
    "P-016": [{"substance": "Sulfa",      "reaction": "rash",  "severity": "mild"}],
    "P-018": [{"substance": "Latex",      "reaction": "contact dermatitis", "severity": "mild"}],
    "P-019": [{"substance": "Codeine",    "reaction": "nausea","severity": "mild"}],
}


def _allergies_for(persona: dict[str, Any], rng: random.Random) -> list[dict[str, str]]:
    pid = persona.get("id", "")
    if pid in _PERSONA_ALLERGIES:
        return list(_PERSONA_ALLERGIES[pid])
    if rng.random() < 0.45:
        return []  # NKDA
    pool = [
        {"substance": "Penicillin", "reaction": "rash"},
        {"substance": "NSAIDs",     "reaction": "GI upset"},
        {"substance": "Iodine contrast", "reaction": "hives"},
        {"substance": "Shellfish",  "reaction": "hives"},
        {"substance": "Amoxicillin","reaction": "rash"},
    ]
    return [rng.choice(pool)]


# Map persona/age cues → a small list of plausible chronic problems.
def _problems_from_modules(persona: dict[str, Any], modules: list[dict[str, Any]],
                            scenario_text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    # Age-related baseline conditions
    if age >= 60:
        out.append({"name": "Essential hypertension", "icd": "I10",  "onset": "chronic"})
        seen.add("hypertension")
    if age >= 65:
        out.append({"name": "Hyperlipidemia",        "icd": "E78.5","onset": "chronic"})
        seen.add("hyperlipidemia")
    # Module-driven primary conditions: take the first 1–2 conditions per module.
    for m in modules:
        for cond in (m.get("conditions") or [])[:2]:
            short = cond.split("(")[0].split(",")[0].strip()
            if not short or short.lower() in seen:
                continue
            out.append({"name": short, "icd": "", "onset": "active"})
            seen.add(short.lower())
    return out[:6]


def _meds_from_modules(persona: dict[str, Any], modules: list[dict[str, Any]],
                        rng: random.Random) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    # Age-based home meds
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    if age >= 60:
        out.append({"name": "Lisinopril",  "dose": "10 mg",  "frequency": "PO daily"})
    if age >= 65:
        out.append({"name": "Atorvastatin","dose": "20 mg",  "frequency": "PO HS"})
    # Module-driven candidates: pick a couple with light filtering for safety.
    pool: list[str] = []
    for m in modules:
        for med in (m.get("medications") or []):
            short = re.split(r"[,;:()/]", med, maxsplit=1)[0].strip()
            if 3 <= len(short) <= 35 and short.lower() not in {x["name"].lower() for x in out}:
                pool.append(short)
    rng.shuffle(pool)
    for m in pool[:3]:
        out.append({"name": m, "dose": "—", "frequency": "as prescribed"})
    return out[:6]


def _default_imms(persona: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": "Influenza", "date": "2025-10-01"},
        {"name": "Tdap",      "date": "2018-04-12"},
    ]


def _social_for(persona: dict[str, Any]) -> dict[str, Any]:
    return {
        "tobacco":     "never",
        "alcohol":     "occasional",
        "drug_use":    "denies",
        "living":      "at home with family",
        "occupation":  "—",
    }


def _family_for(persona: dict[str, Any], modules: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"relation": "father",  "condition": "HTN, CAD"},
        {"relation": "mother",  "condition": "T2DM"},
    ]


def _surgical_for(persona: dict[str, Any], modules: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"procedure": "Appendectomy", "date": "2002-08", "facility": "Outside hospital"}]


def _baseline_vitals(persona: dict[str, Any], condition: str,
                      altered: str | None, encounter: dict[str, Any],
                      rng: random.Random) -> list[dict[str, str]]:
    """Three trended snapshots (T-12h → T-8h → T-4h) randomized inside
    the condition's per-vital range. Trend direction follows the
    condition's `trend` field: worsening drifts toward the high end of
    each range, improving toward the middle, flat keeps it stable."""
    bucket = CLINICAL_RANGES.get(condition) or CLINICAL_RANGES.get("stable_baseline") or {}
    trend = bucket.get("trend", "flat")
    def pick(key: str, idx: int, total: int) -> float:
        rng_pair = bucket.get(key) or [0, 0]
        lo, hi = float(rng_pair[0]), float(rng_pair[1])
        if lo == hi:
            return lo
        # Trend = how far through the range each snapshot sits.
        if trend == "worsening":
            # Earlier snapshots are nearer normal; latest snapshot is most abnormal.
            bias = idx / max(1, total - 1)
        elif trend == "improving":
            # Earlier snapshots are abnormal; latest moves toward normal.
            bias = 1 - (idx / max(1, total - 1))
        elif trend == "fluctuating":
            bias = 0.5 + (rng.random() - 0.5) * 0.6
        else:
            bias = 0.5
        # Center the chosen value at lo + bias*(hi-lo) ± 15% jitter.
        center = lo + bias * (hi - lo)
        jitter = (hi - lo) * 0.15 * (rng.random() * 2 - 1)
        return max(lo, min(hi, center + jitter))
    snapshots = [("t-12h", 0), ("t-8h", 1), ("t-4h", 2)]
    rows: list[dict[str, str]] = []
    for label, idx in snapshots:
        hr   = round(pick("hr",     idx, 3))
        sys_ = round(pick("bp_sys", idx, 3))
        dia  = round(pick("bp_dia", idx, 3))
        rr   = round(pick("rr",     idx, 3))
        t    = pick("t",     idx, 3)
        spo2 = round(pick("spo2",   idx, 3))
        pain = round(pick("pain",   idx, 3))
        rows.append({
            "time": label,
            "t":    f"{t:.1f}",
            "hr":   str(hr),
            "rr":   str(rr),
            "bp":   f"{sys_}/{dia}",
            "spo2": str(spo2),
            "pain": str(pain),
        })
    return rows


def _baseline_labs(persona: dict[str, Any], condition: str,
                    modules: list[dict[str, Any]],
                    rng: random.Random) -> list[dict[str, Any]]:
    """Pull condition-keyed lab panels from CLINICAL_RANGES. Each analyte
    declared as [low, high, flag]; we randomize a value inside that
    range. Always include BMP + CBC even if the condition only specifies
    a few abnormal analytes; fill the rest with normal-range values from
    stable_baseline.
    """
    base = CLINICAL_RANGES.get(condition) or {}
    fallback = CLINICAL_RANGES.get("stable_baseline") or {}
    out: list[dict[str, Any]] = []
    # Merge condition-specific panels over normal-baseline ones.
    panels = dict((fallback.get("labs") or {}))
    for panel_name, analytes in (base.get("labs") or {}).items():
        merged = dict(panels.get(panel_name) or {})
        merged.update(analytes)
        panels[panel_name] = merged
    # Reference range column for the operator UI: pull from stable_baseline.
    base_ranges = (fallback.get("labs") or {})
    for panel_name in ("BMP", "CBC") + tuple(p for p in panels if p not in ("BMP", "CBC")):
        if panel_name not in panels:
            continue
        analytes = panels[panel_name]
        values = []
        for analyte, spec in analytes.items():
            lo, hi, flag = spec[0], spec[1], (spec[2] if len(spec) > 2 else "")
            v = lo + (hi - lo) * rng.random()
            v_str = f"{v:.2f}" if (hi - lo) < 2 and v < 10 else f"{v:.0f}"
            # Pull reference range from stable_baseline if available.
            ref_spec = (base_ranges.get(panel_name) or {}).get(analyte)
            if ref_spec:
                ref = f"{ref_spec[0]}-{ref_spec[1]}"
            else:
                ref = f"{lo}-{hi}"
            values.append({"name": analyte, "v": v_str, "ref": ref, "flag": flag})
        out.append({"panel": panel_name, "time": "T-6h", "values": values})
    return out


# ──────────────────────────────────────────────────────────────────────
# V6 — MAR, IV fluids, tube feeds, weight helper, validator
# ──────────────────────────────────────────────────────────────────────

def _weight_kg_from(weight_str: str) -> float:
    """Parse '74 kg' or '162 lb' → kg float. Default 70 kg if unparseable."""
    if not weight_str:
        return 70.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|lb|lbs)?", weight_str)
    if not m:
        return 70.0
    n = float(m.group(1))
    unit = (m.group(2) or "kg").lower()
    return n if unit == "kg" else round(n * 0.4536, 1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _offset_iso(hours: float) -> str:
    return (datetime.now(timezone.utc).astimezone() + timedelta(hours=hours)
            ).strftime("%Y-%m-%d %H:%M")


def _resolve_drug(name_hint: str) -> tuple[str, dict[str, Any]] | None:
    """Match a free-text drug name from a module against DRUG_DOSES.
    Returns (canonical_name, dose_record) on hit; None if no match."""
    if not name_hint:
        return None
    h = name_hint.lower().strip()
    # Direct exact match
    for canonical in DRUG_DOSES:
        if canonical.startswith("_"):
            continue
        if canonical.lower() == h:
            return canonical, DRUG_DOSES[canonical]
    # Substring (canonical contains hint, or hint contains canonical)
    for canonical in DRUG_DOSES:
        if canonical.startswith("_"):
            continue
        cl = canonical.lower()
        if h in cl or cl in h:
            return canonical, DRUG_DOSES[canonical]
    return None


# Per-condition "always present" meds — applied even if the module list
# doesn't mention them, because they're standard of care for that picture.
_CONDITION_MEDS: dict[str, list[str]] = {
    "sepsis":             ["Piperacillin/Tazobactam", "Vancomycin", "Norepinephrine gtt"],
    "septic_shock":       ["Piperacillin/Tazobactam", "Vancomycin", "Norepinephrine gtt", "Vasopressin gtt"],
    "chf_exacerbation":   ["Furosemide", "Metoprolol succinate", "Lisinopril"],
    "mi_stemi":           ["Aspirin (load)", "Clopidogrel", "Heparin gtt", "Atorvastatin", "Metoprolol tartrate"],
    "stroke_ischemic":    ["Aspirin", "Atorvastatin", "Nicardipine gtt"],
    "gi_bleed_upper":     ["Pantoprazole", "Octreotide gtt"],
    "pneumonia":          ["Ceftriaxone", "Azithromycin", "Acetaminophen"],
    "pe_pulmonary_embolism":["Heparin gtt"],
    "copd_exacerbation":  ["Albuterol", "Ipratropium", "Methylprednisolone"],
    "asthma_exacerbation":["Albuterol", "Ipratropium", "Methylprednisolone"],
    "dka":                ["Insulin regular gtt", "Potassium chloride"],
    "hyperkalemia":       ["Calcium gluconate", "Insulin regular gtt", "Dextrose 50%", "Furosemide"],
    "aki":                ["Furosemide"],
    "anaphylaxis":        ["Epinephrine IM", "Diphenhydramine", "Methylprednisolone"],
    "alcohol_withdrawal": ["Lorazepam", "Thiamine", "Folate", "Multivitamin"],
    "opioid_overdose":    ["Naloxone"],
    "stimulant_intoxication": ["Lorazepam"],
    "delirium":           ["Haloperidol", "Acetaminophen"],
    "post_op_stable":     ["Acetaminophen IV", "Morphine", "Ondansetron"],
    "hypoglycemia":       ["Dextrose 50%"],
    "hyperglycemia_hhs":  ["Insulin regular gtt"],
    "trauma_blunt":       ["Tranexamic acid", "Fentanyl"],
    "ob_postpartum_hemorrhage": ["Oxytocin", "Tranexamic acid"],
    "psychosis_acute":    ["Olanzapine", "Lorazepam"],
}


def _ts_to_iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s).strftime("%Y-%m-%d %H:%M")


def _build_mar(persona: dict[str, Any], modules: list[dict[str, Any]],
                condition: str, overlays: list[str],
                oxygen_drug: str | None, weight_kg: float,
                admit_time: float, care_team: list[dict[str, str]],
                rng: random.Random) -> list[dict[str, Any]]:
    """V6.1 — admission-time-anchored MAR with full administration history.

    For each ordered med:
      ordered_at        = admit_time + order_offset_h (from treatment_timelines)
      first_dose_at     = ordered_at + 0.5 h (typical delay)
      scheduled_times   = first_dose_at + N*interval_h, for next 24 h
      administrations[] = past doses (±15 min jitter from scheduled),
                          each stamped with given_by (RN from care team) +
                          witness (for controlled substances) + status
      current_status    = due_soon | overdue | scheduled | prn_available | infusing
      high_alert        = true for opioids / anticoag / insulin / electrolyte /
                          vasopressor (ISMP categories)

    Source priority (same as v1, with treatment_timelines as the new top-level
    layer that controls order_offset_h + rationale per drug per condition):
      1. treatment_timelines[primary] + per-overlay
      2. _CONDITION_MEDS fallback for conditions without a timeline entry
      3. Oxygen
      4. Post-op DVT prophylaxis + bowel regimen + IS
      5. Age-based home meds
      6. modules[].medications free text (lowest)
    """
    now = time.time()
    # Step 1: assemble the candidate (name, order_offset_h, prn_reasons) list.
    candidates: dict[str, dict[str, Any]] = {}   # canonical_name → meta

    def _add(name: str, order_offset_h: float = 0.5,
              interval_h_override: float | None = None,
              rationale: str = "",
              prn_reasons: list[str] | None = None) -> None:
        if not name:
            return
        key = name.lower().strip()
        if key in candidates:
            return
        candidates[key] = {
            "name":              name,
            "order_offset_h":    order_offset_h,
            "interval_h_override": interval_h_override,
            "rationale":         rationale,
            "prn_reasons":       prn_reasons or [],
        }

    # Pull from treatment timelines first (carries per-drug timing + rationale).
    for timeline_key in ([condition] + overlays):
        for entry in (TREATMENT_TIMELINES.get(timeline_key) or []):
            _add(entry["drug"],
                  order_offset_h=float(entry.get("order_offset_h", 0.5)),
                  interval_h_override=entry.get("interval_h"),
                  rationale=entry.get("rationale", ""),
                  prn_reasons=entry.get("prn_reasons"))
    # Fallback: _CONDITION_MEDS for anything the timelines didn't already cover.
    for n in _CONDITION_MEDS.get(condition, []):
        _add(n)
    for ov in overlays:
        for n in _CONDITION_MEDS.get(ov, []):
            _add(n)
    if oxygen_drug:
        _add(oxygen_drug, order_offset_h=0.0, rationale="Maintain SpO2 target")
    if "post_op_stable" in overlays:
        for n in ("Enoxaparin", "Cefoxitin", "Famotidine", "Docusate",
                   "Sequential compression devices (SCDs)", "Incentive spirometry"):
            _add(n)
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    if age >= 60: _add("Lisinopril",   order_offset_h=0.5, rationale="Home med continued")
    if age >= 65: _add("Atorvastatin", order_offset_h=0.5, rationale="Home med continued")
    for m in modules:
        for med in (m.get("medications") or []):
            short = re.split(r"[,;:()/]", med, maxsplit=1)[0].strip()
            if 3 <= len(short) <= 35:
                _add(short)

    # Step 2: resolve each candidate through DRUG_DOSES and build the full row.
    nurses = [m for m in (care_team or []) if "RN" in (m.get("role") or "")]
    if not nurses:
        nurses = [{"name": "RN Smith", "role": "RN"}]
    out: list[dict[str, Any]] = []
    for i, (key, meta) in enumerate(list(candidates.items())[:16]):
        match = _resolve_drug(meta["name"])
        if match is None:
            out.append({
                "med_id":     f"med_stub_{i:03d}",
                "name":       meta["name"], "dose": "—", "route": "—",
                "frequency":  "as prescribed", "interval_h": None,
                "drug_class": "",
                "high_alert": False,
                "ordered_at": "", "first_dose_at": "",
                "scheduled_times": [], "administrations": [],
                "current_status": "stub", "next_due": "",
                "rationale": meta["rationale"],
            })
            continue
        canonical, rec = match
        interval = (meta["interval_h_override"]
                    if meta["interval_h_override"] is not None
                    else rec.get("interval_h"))
        dose = _dose_for_weight(rec["dose"], weight_kg)
        ordered_at = admit_time + meta["order_offset_h"] * 3600
        # Continuous infusions: started ~ 30 min after order, infusing now.
        if interval is None:
            start_at = ordered_at + 1800
            row = {
                "med_id":      f"med_{re.sub(r'[^a-z0-9]', '_', canonical.lower())}_{i:03d}",
                "name":        canonical,
                "dose":        dose,
                "route":       rec.get("route") or "IV",
                "frequency":   rec.get("frequency") or "continuous",
                "interval_h":  None,
                "drug_class":  rec.get("class") or "",
                "high_alert":  (rec.get("class") or "") in _HIGH_ALERT_CLASSES,
                "rationale":   meta["rationale"],
                "ordered_at":  _ts_to_iso(ordered_at),
                "first_dose_at": _ts_to_iso(start_at),
                "scheduled_times": [],
                "administrations": [{
                    "ts":       _ts_to_iso(start_at),
                    "given_by": rng.choice(nurses)["name"],
                    "witness":  None,
                    "status":   "started",
                    "site":     "central line" if "vaso" in (rec.get("class") or "") else "PIV",
                    "note":     meta["rationale"][:60],
                }],
                "current_status": "infusing",
                "next_due":   "continuous",
            }
            out.append(row)
            continue
        # Scheduled or PRN intermittent med.
        is_prn = "prn" in (rec.get("frequency") or "").lower() or bool(meta["prn_reasons"])
        first_dose_at = ordered_at + 1800     # 30 min standard delay
        # Build scheduled clock times: for non-PRN, every interval since first
        # dose; PRN entries get the "PRN" marker instead.
        scheduled_times_iso: list[str] = []
        past_admins: list[dict[str, Any]] = []
        needs_witness = (rec.get("class") or "") == "opioid" \
                        or canonical in ("Insulin regular gtt",)
        if is_prn:
            # Generate 0-3 random PRN administrations between order and now.
            window_s = max(0.0, now - first_dose_at)
            n_doses = min(3, int(window_s // (interval * 3600))) if interval else 0
            for _ in range(rng.randint(0, n_doses)):
                t = first_dose_at + rng.uniform(0.5, max(0.6, window_s / 3600 - 0.5)) * 3600
                if t >= now:
                    continue
                past_admins.append({
                    "ts":       _ts_to_iso(t),
                    "given_by": rng.choice(nurses)["name"],
                    "witness":  rng.choice(nurses)["name"] if needs_witness else None,
                    "status":   "given",
                    "site":     _site_for_route(rec.get("route") or "", rng),
                    "note":     rng.choice(meta["prn_reasons"]) if meta["prn_reasons"] else "PRN",
                })
            current_status = "prn_available"
            next_due_iso   = "PRN available"
        else:
            t = first_dose_at
            while t <= now + 24 * 3600:
                scheduled_times_iso.append(_ts_to_iso(t))
                t += interval * 3600
            # Past administrations: every scheduled time before now, with
            # ±15 min jitter.
            for sched_t in [first_dose_at + k * interval * 3600
                             for k in range(0, int((now - first_dose_at) / (interval * 3600)) + 1)]:
                if sched_t >= now:
                    continue
                actual_t = sched_t + rng.uniform(-900, 900)
                past_admins.append({
                    "ts":       _ts_to_iso(actual_t),
                    "given_by": rng.choice(nurses)["name"],
                    "witness":  rng.choice(nurses)["name"] if needs_witness else None,
                    "status":   "given",
                    "site":     _site_for_route(rec.get("route") or "", rng),
                    "note":     "",
                })
            # next_due = first future scheduled time
            future_times = [t for t in scheduled_times_iso
                             if datetime.strptime(t, "%Y-%m-%d %H:%M").timestamp() > now]
            next_due_iso = future_times[0] if future_times else _ts_to_iso(t)
            secs_to_next = max(0, datetime.strptime(next_due_iso, "%Y-%m-%d %H:%M").timestamp() - now)
            if secs_to_next < 3600:
                current_status = "due_soon"
            elif secs_to_next > 6 * 3600 and past_admins:
                current_status = "scheduled"
            else:
                current_status = "scheduled"
            # Check for any past admin that should have happened but is too old.
            for sched_t in [first_dose_at + k * interval * 3600
                             for k in range(0, int((now - first_dose_at) / (interval * 3600)) + 1)]:
                if now - sched_t > (interval * 3600 + 1800):  # > 30 min past schedule
                    current_status = "overdue" if not past_admins else current_status

        row = {
            "med_id":         f"med_{re.sub(r'[^a-z0-9]', '_', canonical.lower())}_{i:03d}",
            "name":           canonical,
            "dose":           dose,
            "route":          rec.get("route") or "PO",
            "frequency":      rec.get("frequency") or "",
            "interval_h":     interval,
            "drug_class":     rec.get("class") or "",
            "high_alert":     (rec.get("class") or "") in _HIGH_ALERT_CLASSES,
            "rationale":      meta["rationale"],
            "ordered_at":     _ts_to_iso(ordered_at),
            "first_dose_at":  _ts_to_iso(first_dose_at),
            "scheduled_times":scheduled_times_iso,
            "administrations":past_admins,
            "current_status": current_status,
            "next_due":       next_due_iso,
        }
        out.append(row)
    return out


def _site_for_route(route: str, rng: random.Random) -> str:
    r = (route or "").upper()
    if "IV" in r:   return rng.choice(["R AC 18g", "L AC 18g", "R forearm 20g", "L forearm 20g"])
    if "IM" in r:   return rng.choice(["R deltoid", "L deltoid", "R ventrogluteal"])
    if "SC" in r:   return rng.choice(["R abdomen", "L abdomen", "R thigh"])
    if "PO" in r:   return "PO"
    if "INH" in r:  return "neb / inhaler"
    if "NC" in r:   return "nasal cannula"
    if "PR" in r:   return "rectal"
    return r or "—"


def _dose_for_weight(template: str, kg: float) -> str:
    """If template contains 'units/kg' or 'mcg/kg/min' etc., substitute
    the patient's weight to produce a concrete starting dose. Otherwise
    return the template as-is.
    """
    if "/kg" not in template:
        return template
    # Heparin gtt: "18 units/kg/hr" → "18 units/kg/hr (≈ 1260 units/hr at 70 kg)"
    m = re.match(r"([\d.]+)\s*([a-zA-Z]+)\/kg(\/[a-zA-Z]+)?", template)
    if not m:
        return template
    per_kg, unit, suffix = float(m.group(1)), m.group(2), (m.group(3) or "")
    starting = per_kg * kg
    if starting >= 100:
        return f"{template} (≈ {round(starting)} {unit}{suffix} at {kg:.0f} kg)"
    return f"{template} (≈ {starting:.1f} {unit}{suffix} at {kg:.0f} kg)"


def _build_iv_fluids(persona: dict[str, Any], condition: str,
                      weight_kg: float, rng: random.Random) -> list[dict[str, Any]]:
    """Pick IV fluids whose indications include this condition. Compute
    realistic bag-hung-at + infused-so-far values."""
    fluids = (IV_FLUID_CATALOG.get("fluids") or [])
    matched = [f for f in fluids if condition in (f.get("indications") or [])]
    if not matched:
        # Stable patient on routine maintenance.
        matched = [f for f in fluids if "stable_baseline" in (f.get("indications") or [])][:1]
    out: list[dict[str, Any]] = []
    for f in matched[:2]:
        rate = f.get("default_rate_ml_hr") or 100
        vtbi = f.get("bag_volume_ml") or 1000
        hung_h_ago = round(rng.uniform(0.5, max(0.6, vtbi / rate - 0.5)), 1)
        infused = round(min(vtbi, rate * hung_h_ago))
        remaining_h = round((vtbi - infused) / max(1, rate), 1)
        out.append({
            "solution":               f["name"],
            "rate_ml_hr":             rate,
            "vtbi_ml":                vtbi,
            "infused_ml":             infused,
            "started_at":             _offset_iso(-hung_h_ago),
            "expected_complete_at":   _offset_iso(remaining_h),
            "line_site":              f.get("line_site_default") or "PIV",
            "indication":             condition,
        })
    return out


def _build_tube_feeds(persona: dict[str, Any], condition: str,
                       rng: random.Random) -> list[dict[str, Any]]:
    """Pick tube-feed formula whose indications include this condition.
    Most scenarios don't need a tube feed; return empty unless a match."""
    formulas = (TUBE_FEED_CATALOG.get("formulas") or [])
    matched = [f for f in formulas if condition in (f.get("indications") or [])]
    if not matched:
        return []
    f = matched[0]
    started_h_ago = round(rng.uniform(2, 10), 1)
    rate = f.get("default_rate_ml_hr") or 30
    infused = round(rate * started_h_ago)
    return [{
        "formula":             f["name"],
        "rate_ml_hr":          rate,
        "target_rate_ml_hr":   f.get("default_target_rate_ml_hr"),
        "daily_volume_ml":     f.get("daily_volume_ml"),
        "route":               f.get("route") or "NG",
        "flush_volume_ml":     f.get("flush_volume_ml"),
        "flush_interval_h":    f.get("flush_interval_h"),
        "started_at":          _offset_iso(-started_h_ago),
        "infused_ml":          infused,
        "indication":          condition,
    }]


# Allergy → drug class match. The class strings here must match what the
# drug catalog records on each med so the validator can detect collisions.
_ALLERGY_CLASS_MAP: dict[str, list[str]] = {
    "penicillin": ["PCN antibiotic"],
    "pcn":        ["PCN antibiotic"],
    "amoxicillin":["PCN antibiotic"],
    "sulfa":      ["sulfonamide"],
    "nsaid":      ["NSAID"],
    "aspirin":    ["antiplatelet", "NSAID"],
    "ibuprofen":  ["NSAID"],
    "morphine":   ["opioid"],
    "codeine":    ["opioid"],
    "statin":     ["statin"],
    "iodine":     ["contrast"],
    "contrast":   ["contrast"],
    "latex":      [],
}


def validate_chart_seed(seed: ChartSeed) -> dict[str, Any]:
    """Walk the seed, auto-correct fixable mistakes, surface anything
    that needs operator judgment. Returns a SeedReport dict that the
    operator UI will render on the ops page.
    """
    warnings: list[str] = []
    corrections: list[str] = []
    errors: list[str] = []

    # 1) MAR stubs — drugs that didn't resolve through the catalog get
    # auto-defaulted to PO daily (clearly a placeholder; flag it).
    for med in (seed.get("medications") or []):
        if med.get("status") == "stub" or med.get("dose") == "—":
            med["dose"] = med.get("dose") if med.get("dose") not in ("—", "", None) else "see order"
            med["route"] = med.get("route") if med.get("route") not in ("—", "", None) else "PO"
            med["frequency"] = med.get("frequency") or "as prescribed"
            warnings.append(
                f"MAR: '{med.get('name')}' is not in the drug catalog — "
                f"defaulted to {med['route']} {med['frequency']}. Add to "
                f"portal/data/drug_doses.json for a proper record."
            )

    # 2) Allergy ↔ MAR drug-class collisions
    allergies = (seed.get("allergies") or [])
    for allergy in allergies:
        akey = (allergy.get("substance") or allergy.get("name") or "").lower()
        classes = []
        for keyword, cls_list in _ALLERGY_CLASS_MAP.items():
            if keyword in akey:
                classes += cls_list
        for med in (seed.get("medications") or []):
            mcls = (med.get("drug_class") or "").lower()
            if any(c.lower() in mcls for c in classes):
                warnings.append(
                    f"ALLERGY collision: patient is allergic to "
                    f"'{allergy.get('substance') or akey}' but the MAR has "
                    f"'{med.get('name')}' ({med.get('drug_class')}). Review."
                )

    # 3) Vitals — every recorded value should fall inside the condition's
    # range. The seeder already does this, but the validator double-checks.
    condition = seed.get("condition") or "stable_baseline"
    bucket = CLINICAL_RANGES.get(condition) or {}
    for snap in (seed.get("vitals_baseline") or []):
        for key, range_key in (("hr", "hr"), ("rr", "rr"), ("spo2", "spo2")):
            r = bucket.get(range_key)
            if not r:
                continue
            try:
                v = float(snap.get(key, "0"))
            except ValueError:
                continue
            if v < r[0] * 0.85 or v > r[1] * 1.15:
                corrections.append(f"Vitals: {key}={snap.get(key)} at {snap.get('time')} outside expected range — left as-is for variability.")

    # 4) IV / feed timing sanity
    for iv in (seed.get("iv_fluids") or []):
        if iv.get("infused_ml", 0) > iv.get("vtbi_ml", 0):
            iv["infused_ml"] = iv.get("vtbi_ml", 0)
            corrections.append(f"IV {iv.get('solution')}: infused_ml capped at vtbi_ml.")

    # 5) Biographic consistency — patient name should appear in at least
    # one note, and condition should be reflected in chief_complaint.
    chief = (seed.get("chief_complaint") or "").lower()
    notes_text = " ".join(n.get("body", "") for n in (seed.get("notes_recent") or [])).lower()
    if seed.get("name") and seed["name"].split()[-1].lower() not in notes_text:
        warnings.append(f"Notes don't reference the patient name '{seed.get('name')}' — admit note may need a refresh.")
    if condition != "stable_baseline" and condition.split("_")[0] not in chief and condition.split("_")[0] not in notes_text:
        warnings.append(f"Chief complaint / notes don't mention the seeded condition '{condition}'. Refine the scenario notes to align.")

    return {
        "condition":     condition,
        "warnings":      warnings,
        "errors":        errors,
        "auto_corrections": corrections,
        "generated_at":  _now_iso(),
    }


def _sex_word(sex: str) -> str:
    return {"F": "woman", "M": "man"}.get((sex or "U").upper(), "patient")


def _altered_state_line(altered: str | None) -> str:
    return {
        "delirium":
            "On arrival the patient is confused with fluctuating attention; "
            "delirium precautions are in place and CAM is monitored per shift.",
        "alcohol-withdrawal":
            "The patient is tremulous and reports visual disturbances; CIWA-Ar "
            "scoring is ordered q4h with symptom-triggered management.",
        "stimulant-intoxication":
            "The patient is agitated with pressured speech and is intermittently "
            "guarded; continuous monitoring is in place.",
        "depression-passive-si":
            "The patient has a flat affect; a safety screen is documented and "
            "passive ideation is being monitored.",
        "psychosis":
            "The patient shows loose associations and is guarded; a 1:1 sitter "
            "and a calm low-stimulation environment are in place.",
        "hostile":
            "Interactions are strained; de-escalation and clear communication "
            "are emphasized.",
    }.get(altered or "", "")


def _chief_complaint(persona: dict[str, Any], modules: list[dict[str, Any]],
                      scenario_text: str) -> str:
    """A short presenting concern for the patient banner."""
    for m in modules:
        for cond in (m.get("conditions") or []):
            short = cond.split("(")[0].split(",")[0].strip()
            if 3 <= len(short) <= 48:
                return short[0].upper() + short[1:]
    if scenario_text:
        first = re.split(r"[.;\n]", scenario_text.strip(), maxsplit=1)[0].strip()
        if 3 <= len(first) <= 70:
            return first
    ks = persona.get("knowledgeScope", "")
    if ks:
        return ks.split(";")[0].strip()[:60] or "Evaluation and management"
    return "Evaluation and management"


def _baseline_notes(persona: dict[str, Any], name: str, chief: str,
                     scenario_text: str, encounter: dict[str, Any],
                     modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Two pre-existing signed notes: an admission H&P and a nursing
    admission note. Both carry the scenario detail so the student opens a
    chart that reflects the scenario being run."""
    return [
        {
            "note_id":   "n_admit_hp",
            "note_type": "Admission H&P",
            "author":    "Admitting provider",
            "ts":        "T-12h",
            "body":      _admit_note_body(persona, name, chief, scenario_text,
                                          encounter, modules),
            "signed":    True,
        },
        {
            "note_id":   "n_admit_nursing",
            "note_type": "Nursing Admission Note",
            "author":    "Admitting RN",
            "ts":        "T-11h",
            "body":      _nursing_note_body(name, chief, encounter, persona),
            "signed":    True,
        },
    ]


def _admit_note_body(persona: dict[str, Any], name: str, chief: str,
                      scenario_text: str, encounter: dict[str, Any],
                      modules: list[dict[str, Any]]) -> str:
    age = persona.get("ageRange", "—")
    sex = persona.get("sex") or _sex_from_voice(persona)
    altered = persona.get("alteredState")
    hpi = (scenario_text or "").strip() or (
        f"{persona.get('knowledgeScope', 'presents for evaluation')}.")
    altered_line = _altered_state_line(altered)
    ap_lines = []
    for m in modules:
        title = m.get("title") or m.get("id", "")
        summ = (m.get("summary") or "").split(".")[0]
        ap_lines.append(f"  - {title}: {summ}." if summ else f"  - {title}.")
    ap = "\n".join(ap_lines) if ap_lines else "  - See plan; reassess and escalate per protocol."
    parts = [
        f"CHIEF COMPLAINT: {chief}",
        "",
        "HISTORY OF PRESENT ILLNESS:",
        f"{name} is a {age}-year-old {_sex_word(sex)} who presents to "
        f"{encounter.get('location', 'the unit')}. {hpi}",
    ]
    if altered_line:
        parts += ["", altered_line]
    parts += ["", "ASSESSMENT & PLAN:", ap]
    return "\n".join(parts).strip()


def _nursing_note_body(name: str, chief: str, encounter: dict[str, Any],
                        persona: dict[str, Any]) -> str:
    altered = persona.get("alteredState")
    safety = persona.get("safetyClass", "baseline")
    lines = [
        f"Patient {name} admitted to {encounter.get('location', 'the unit')} "
        f"for: {chief}.",
        f"Encounter: {encounter.get('type', 'Inpatient')}, "
        f"{encounter.get('los', '')}. Isolation: {encounter.get('isolation', 'Standard')}.",
        "Orientation, fall-risk, and skin assessment completed on admission. "
        "Call light and belongings within reach.",
    ]
    if altered:
        lines.append(_altered_state_line(altered))
    if safety == "high-risk":
        lines.append("HIGH-RISK encounter — instructor in the loop; "
                      "escalation pathway reviewed with the team.")
    return "\n".join(lines).strip()


def _care_team(persona: dict[str, Any], encounter: dict[str, Any],
                rng: random.Random) -> list[dict[str, str]]:
    return [
        {"role": "Attending", "name": rng.choice(["Dr. R. Bashir", "Dr. S. Park", "Dr. P. Adeyemi", "Dr. K. Almeida"])},
        {"role": "PCP",       "name": rng.choice(["Dr. T. Okafor", "Dr. M. Chen", "Dr. L. Sandberg"])},
        {"role": "RN",        "name": rng.choice(["M. Petrosian", "D. Park", "L. Silvera"])},
    ]


def _encounter_meta(persona: dict[str, Any], modules: list[dict[str, Any]],
                     scenario_text: str, ehr_id: str) -> dict[str, Any]:
    mod_ids = {m.get("id") for m in modules}
    safety = persona.get("safetyClass", "baseline")
    altered = persona.get("alteredState")
    # Pick a setting based on module mix.
    if "M32" in mod_ids:
        location, kind = ("ICU-3 / Bed 04", "ICU")
    elif "M22" in mod_ids:
        location, kind = ("Med-Surg 4 / Bed 12", "Inpatient")
    elif "M08" in mod_ids:
        location, kind = ("PACU / Bay 6", "Postop")
    elif "M39" in mod_ids:
        location, kind = ("Behavioral Health 2", "Inpatient")
    else:
        location, kind = ("Med-Surg 6 / Bed 12", "Inpatient")
    isolation = "Droplet" if altered in {"psychosis"} else "Standard"
    if safety == "high-risk":
        isolation = "Standard · 1:1 sitter"
    # Encounter reason: prefer the scenario's own words, fall back to the
    # selected module's summary.
    reason = ""
    if scenario_text:
        first = re.split(r"[.;\n]", scenario_text.strip(), maxsplit=1)[0].strip()
        if 3 <= len(first) <= 90:
            reason = first
    if not reason:
        reason = _first_module_summary(modules) or "as documented in admission note"
    return {
        "location":  location,
        "type":      kind,
        "los":       "Day 2" if kind != "Postop" else "POD 1",
        "isolation": isolation,
        "reason":    reason,
    }


def _first_module_summary(modules: list[dict[str, Any]]) -> str:
    for m in modules:
        s = m.get("summary") or ""
        if s:
            return s.split(".")[0]
    return ""


def _weight_for(persona: dict[str, Any], rng: random.Random) -> str:
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    if age < 12:
        return f"{rng.uniform(18, 38):.1f} kg"
    return f"{rng.uniform(58, 92):.1f} kg"


def _height_for(persona: dict[str, Any], rng: random.Random) -> str:
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    if age < 12:
        return f"{rng.uniform(120, 150):.0f} cm"
    return f"{rng.uniform(155, 188):.0f} cm"


def _bsa_for(persona: dict[str, Any], rng: random.Random) -> str:
    return f"{rng.uniform(1.5, 2.1):.2f}"


def _insurance_for(persona: dict[str, Any]) -> str:
    age_str = persona.get("ageRange", "40")
    try:
        age = int(re.sub(r"\D", "", str(age_str).split("-", 1)[-1]) or "40")
    except ValueError:
        age = 40
    if age >= 65:
        return "Medicare A+B / AARP supp"
    if age < 18:
        return "Medicaid MCO"
    return "BlueCross PPO"


# ──────────────────────────────────────────────────────────────────────
# Convenience: build seed for the primary persona of a ControlSession
# ──────────────────────────────────────────────────────────────────────

def seed_from_session(session: Any, *, ehr_id: str) -> ChartSeed | None:
    """Pick the first selected persona; build a seed using selected modules."""
    if not session.selected_personas:
        return None
    pid = session.selected_personas[0]
    persona = library.get_persona(pid)
    if persona is None:
        return None
    modules = [m for m in (library.get_module(mid) for mid in session.selected_modules) if m]
    return seed_from_persona(persona, modules=modules,
                             scenario_text=session.scenario_text, ehr_id=ehr_id)


def patient_persona_id(session: Any) -> str | None:
    """M58 — Resolve which persona on a session is THE PATIENT.

    The session can carry several personas (the patient + family
    role-players + clinicians for engagement turns). Only the
    patient has a prescribed MAR; other personas show up in
    `selected_personas` for chat but don't have medications.

    Resolution order:
      1. `session.patient_persona_id` if set (v7 default — the
         wizard's "Patient" picker writes this).
      2. First entry in `selected_personas` (v6 single-patient
         convention — the first persona was the patient).
      3. None — caller decides what to do (usually skip).
    """
    pid = getattr(session, "patient_persona_id", None)
    if pid:
        return str(pid).strip() or None
    chosen = getattr(session, "selected_personas", None) or []
    if chosen:
        return str(chosen[0]).strip() or None
    return None


def seeds_for_patient_only(session: Any, *,
                            ehr_id: str | None = None
                            ) -> list[dict[str, Any]]:
    """M58 — Same shape as `seeds_for_all_personas` but only returns
    the entry for `patient_persona_id(session)`. Used by the
    encounter Medications card and the M47 med cart so neither
    surface shows MAR rows for family or clinician personas.

    Returns an empty list when no patient persona resolves."""
    target = patient_persona_id(session)
    if not target:
        return []
    return [
        p for p in seeds_for_all_personas(session, ehr_id=ehr_id)
        if (p.get("character_id") or "").strip() == target
    ]


def seeds_for_all_personas(session: Any, *,
                            ehr_id: str | None = None
                            ) -> list[dict[str, Any]]:
    """V6.1.6 — return one chart-seed-lite per character in the session.
    Used by med-cart devices (Pyxis et al.) to show every patient's MAR
    on the cart at once, without picking one. Each entry includes:
      - character_id (the persona id)
      - name, mrn
      - location_label (e.g. 'Bed 3' if persona.location set; else a
        short label derived from the name)
      - medications (the MAR list from _build_mar — name, dose, route,
        scheduled_times, current_status, high_alert, etc.)

    Cheaper than rebuilding the entire ChartSeed per persona: we only
    surface the fields the cart UI actually displays.
    """
    out: list[dict[str, Any]] = []
    if not session.selected_personas:
        return out
    modules = [m for m in (library.get_module(mid) for mid in session.selected_modules) if m]
    for idx, pid in enumerate(session.selected_personas, start=1):
        persona = library.get_persona(pid)
        if persona is None:
            continue
        try:
            seed = seed_from_persona(persona, modules=modules,
                                       scenario_text=session.scenario_text,
                                       ehr_id=ehr_id or "")
        except Exception:
            seed = None
        if not seed:
            continue
        out.append({
            "character_id":   pid,
            "name":           seed.get("name") or persona.get("name") or pid,
            "mrn":            seed.get("mrn") or "",
            "location_label": persona.get("location")
                               or seed.get("encounter", {}).get("location")
                               or f"Bed {idx}",
            "medications":    seed.get("medications") or [],
        })
    return out
