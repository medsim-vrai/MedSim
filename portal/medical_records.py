"""M61 — Medical Records helper module.

Operator: "Medical records entry page to select from patient characters
and give status of pending actions – meds, labs etc. The MAR in the
medical records should use the standard three shift time structure for
medication administration. And for the case define the best practice
route of administration and time frame, like BID, TID, QD, etc. For
Tube feed and IV the total volume rate, fluid type and any associated
medication to infused with rate and time and total dose."

This module computes the view-model data the `/portal/medical_records`
template needs:

  - `SHIFTS` — the three standard nursing shifts.
  - `parse_frequency()` — maps "BID"/"TID"/"q6h"/etc. → scheduled times.
  - `shift_for_hh_mm()` — buckets a clock time into Day / Evening / Night.
  - `is_continuous_infusion()` — IV drips + tube feeds render specially.
  - `infusion_summary()` — volume + rate + fluid + additives for the
    continuous-infusion section.
  - `patient_status()` — counts of pending actions (due soon,
    undocumented this shift, pending labs).
  - `patients_for_picker()` — list of every patient across single or
    multi-patient mode for the entry-page picker.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable


# Nursing shifts — standard 8-hour rotation, Day starts at 07:00.
# Tuple is (label, start_hour, end_hour). Night wraps midnight.
SHIFTS: list[tuple[str, int, int]] = [
    ("Day",     7,  15),   # 07:00 – 14:59
    ("Evening", 15, 23),   # 15:00 – 22:59
    ("Night",   23,  7),   # 23:00 – 06:59 (wraps midnight)
]


# Canonical frequency → list of "HH:MM" clock times. Doses are spaced
# evenly so a typical med-pass landing zone fits in the right shift
# (09:00 for QD, 09:00+21:00 for BID, etc.). Real bedside MARs use the
# unit's standard times; these defaults match common adult-floor
# convention.
_FREQUENCY_SCHEDULES: dict[str, list[str]] = {
    "QD":   ["09:00"],
    "QAM":  ["09:00"],
    "QHS":  ["21:00"],
    "HS":   ["21:00"],
    "BID":  ["09:00", "21:00"],
    "TID":  ["09:00", "13:00", "21:00"],
    "QID":  ["09:00", "13:00", "17:00", "21:00"],
    "Q4H":  ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
    "Q6H":  ["00:00", "06:00", "12:00", "18:00"],
    "Q8H":  ["06:00", "14:00", "22:00"],
    "Q12H": ["09:00", "21:00"],
}


# Frequency strings the seed builder emits that mean "continuous".
_CONTINUOUS_TOKENS = {
    "continuous", "drip", "infusion", "infusing",
}


# PRN / as-needed — no scheduled slot.
_PRN_TOKENS = {"prn", "as needed", "as prescribed", "as ordered"}


def _normalize_frequency(freq: str | None) -> str:
    """Uppercase, strip route prefixes, collapse whitespace.
    Examples:
      "PO BID"     → "BID"
      "IV q6h"     → "Q6H"
      "PO daily"   → "QD"
      "q8h IV"     → "Q8H"
      "BID PO HS"  → "BID"  (first matching token wins)
    """
    if not freq:
        return ""
    f = freq.strip().upper()
    # Route prefixes / suffixes — drop them.
    f = re.sub(r"\b(PO|IV|IM|SQ|SC|SUBQ|TOPICAL|TOP|PR|SL|INHALED)\b",
                " ", f)
    f = re.sub(r"\s+", " ", f).strip()
    # "daily" → QD
    if re.fullmatch(r"DAILY", f) or re.fullmatch(r"EVERY DAY", f):
        return "QD"
    if re.fullmatch(r"BEDTIME", f) or re.fullmatch(r"AT BEDTIME", f):
        return "HS"
    if re.fullmatch(r"TWICE DAILY|TWICE A DAY|BD", f):
        return "BID"
    if re.fullmatch(r"THREE TIMES DAILY|THREE TIMES A DAY", f):
        return "TID"
    if re.fullmatch(r"FOUR TIMES DAILY|FOUR TIMES A DAY", f):
        return "QID"
    # Already a canonical token?
    if f in _FREQUENCY_SCHEDULES:
        return f
    # Strip "every" — "every 6 hours" → "q6h"
    m = re.fullmatch(r"EVERY\s+(\d+)\s*H(?:OURS?)?", f)
    if m:
        return f"Q{m.group(1)}H"
    # "q6h" came in lower-case
    m = re.fullmatch(r"Q\s*(\d+)\s*H", f)
    if m:
        return f"Q{m.group(1)}H"
    return f   # caller decides whether to fall through


def parse_frequency(freq: str | None,
                    interval_h: float | int | None = None
                    ) -> dict[str, Any]:
    """Map a freq string + optional interval_h → schedule dict.

    Returns:
      {
        "canonical": "BID" | "TID" | "Q6H" | "" | ...,
        "label":     "BID" | "Q6H" | "Continuous" | "PRN" | "Other",
        "times":     ["09:00", "21:00"] | [],
        "is_continuous": True/False,
        "is_prn":        True/False,
      }
    """
    raw = (freq or "").strip()
    lower = raw.lower()
    out: dict[str, Any] = {
        "canonical": "", "label": raw or "—",
        "times": [], "is_continuous": False, "is_prn": False,
    }
    # Continuous infusion takes precedence — IV drips / tube feeds
    # use interval_h=None with a "continuous" / "drip" frequency.
    if (interval_h is None
            and any(tok in lower for tok in _CONTINUOUS_TOKENS)):
        out.update({"label": "Continuous", "is_continuous": True})
        return out
    # PRN — no schedule. BUT: if the seed gave us a concrete
    # `interval_h`, that's a real schedule — skip PRN detection and
    # let the interval fallback compute slots. The seed builder uses
    # "as prescribed" as a generic placeholder string even on rows
    # that have a real interval, so we have to override it explicitly.
    has_interval = interval_h is not None and float(interval_h) > 0
    if (not has_interval
            and any(tok in lower for tok in _PRN_TOKENS)
            and "qd" not in lower):
        # `as prescribed` is the seed builder's "I don't know" sentinel
        # — treat as PRN for scheduling purposes.
        out.update({"label": "PRN" if "prn" in lower else (raw or "—"),
                    "is_prn": True})
        return out
    # Canonical mapping.
    canonical = _normalize_frequency(raw)
    if canonical in _FREQUENCY_SCHEDULES:
        out.update({
            "canonical": canonical,
            "label":     canonical,
            "times":     list(_FREQUENCY_SCHEDULES[canonical]),
        })
        return out
    # interval_h fallback — if the seed didn't give us a canonical
    # token but did give a numeric interval, derive a Q<N>H slot list.
    if interval_h is not None and interval_h > 0:
        n = max(1, int(round(24 / float(interval_h))))
        # spread `n` doses evenly through 24 h, aligning the first
        # dose to 09:00 so it lands in the morning med pass.
        step_h = 24 // n
        start_h = 9 % step_h or step_h
        times = [
            f"{(start_h + step_h * i) % 24:02d}:00"
            for i in range(n)
        ]
        out.update({
            "canonical": f"Q{int(round(float(interval_h)))}H",
            "label":     f"q{int(round(float(interval_h)))}h",
            "times":     times,
        })
        return out
    return out   # unrecognized — caller renders the raw label


def shift_for_hh_mm(hh_mm: str) -> str | None:
    """Return the shift label ("Day"/"Evening"/"Night") that contains
    the given clock time, or None for malformed input."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hh_mm.strip())
    if not m:
        return None
    h = int(m.group(1))
    if 7 <= h < 15:
        return "Day"
    if 15 <= h < 23:
        return "Evening"
    return "Night"   # 23:00 - 06:59


def bucket_med_times_by_shift(times: Iterable[str]) -> dict[str, list[str]]:
    """Bucket a list of HH:MM times into the three nursing shifts.
    Returns a dict keyed by shift label, values are the times that
    fall in that shift (in input order)."""
    out: dict[str, list[str]] = {label: [] for (label, _s, _e) in SHIFTS}
    for t in times:
        shift = shift_for_hh_mm(t)
        if shift:
            out[shift].append(t)
    return out


def is_continuous_infusion(med: dict[str, Any]) -> bool:
    """True for IV drips / continuous infusions. Used to route the med
    into the "Infusions" detail block instead of the shift-MAR table."""
    interval_h = med.get("interval_h")
    freq = (med.get("frequency") or "").lower()
    if interval_h is None and any(tok in freq for tok in _CONTINUOUS_TOKENS):
        return True
    # Some seeds set `current_status="infusing"` for IV drips.
    if (med.get("current_status") or "").lower() == "infusing":
        return True
    return False


def infusion_summary(med: dict[str, Any]) -> dict[str, Any]:
    """Pull out the fields the Infusions section needs for one IV
    drip / continuous med:
       name, dose, rate, route, fluid, started_at, total_dose.
    Missing fields are returned as empty strings."""
    return {
        "name":         med.get("name") or "",
        "dose":         med.get("dose") or med.get("strength") or "",
        "route":        med.get("route") or "IV",
        "drug_class":   med.get("drug_class") or "",
        "high_alert":   bool(med.get("high_alert")),
        "rationale":    med.get("rationale") or "",
        "current_status": med.get("current_status") or "",
        "first_dose_at": med.get("first_dose_at") or "",
        "administrations": list(med.get("administrations") or []),
    }


def tube_feed_summary(tf: dict[str, Any]) -> dict[str, Any]:
    """Surface the volume + rate + formula + route fields for the
    Tube Feeds section."""
    return {
        "formula":         tf.get("formula") or "",
        "rate_ml_hr":      tf.get("rate_ml_hr"),
        "target_rate_ml_hr": tf.get("target_rate_ml_hr"),
        "daily_volume_ml": tf.get("daily_volume_ml"),
        "route":           tf.get("route") or "NG",
        "flush_volume_ml": tf.get("flush_volume_ml"),
        "flush_interval_h": tf.get("flush_interval_h"),
        "started_at":      tf.get("started_at") or "",
        "infused_ml":      tf.get("infused_ml"),
        "indication":      tf.get("indication") or "",
    }


def med_view_model(med: dict[str, Any]) -> dict[str, Any]:
    """Build the per-med view-model the shift-MAR template iterates:
       name, dose, route, frequency_label, schedule per shift,
       is_continuous, is_prn, high_alert, current_status, last_given,
       rationale.
    """
    sched = parse_frequency(med.get("frequency"), med.get("interval_h"))
    shifts = bucket_med_times_by_shift(sched["times"])
    admins = med.get("administrations") or []
    last_given = ""
    if admins:
        a = admins[-1]
        last_given = a.get("ts") or a.get("given_by") or ""
    return {
        "med_id":          med.get("med_id") or "",
        "name":            med.get("name") or "",
        "dose":            med.get("dose") or "",
        "route":           med.get("route") or "",
        "frequency_label": sched["label"],
        "frequency_canonical": sched["canonical"],
        "shifts":          shifts,
        "is_continuous":   sched["is_continuous"] or is_continuous_infusion(med),
        "is_prn":          sched["is_prn"],
        "high_alert":      bool(med.get("high_alert")),
        "current_status":  med.get("current_status") or "",
        "last_given":      last_given,
        "rationale":       med.get("rationale") or "",
        "drug_class":      med.get("drug_class") or "",
    }


def patient_status(meds: list[dict[str, Any]],
                    labs: list[dict[str, Any]] | None = None,
                    now: _dt.datetime | None = None
                    ) -> dict[str, Any]:
    """Compute "pending actions" counters for the patient picker.

    Args:
      meds: list of seed-shaped medication dicts.
      labs: list of lab orders (if available; we use it loosely).
      now:  optional injected wall-clock for tests.

    Returns:
      {
        "med_count":             N,    # total active meds
        "scheduled_today":       N,    # rows with at least one shift slot
        "continuous_count":      N,    # IV / tube feed infusions
        "prn_count":             N,
        "due_in_current_shift":  N,    # scheduled times whose shift ⊇ now
        "current_shift":         "Day"|"Evening"|"Night",
        "labs_pending":          N,    # ordered + not yet resulted
      }
    """
    if now is None:
        now = _dt.datetime.now()
    cur_shift = shift_for_hh_mm(f"{now.hour:02d}:{now.minute:02d}") or "Day"
    scheduled_today = 0
    continuous_count = 0
    prn_count = 0
    due_in_shift = 0
    for med in meds:
        vm = med_view_model(med)
        if vm["is_continuous"]:
            continuous_count += 1
            continue
        if vm["is_prn"]:
            prn_count += 1
            continue
        shift_slots = vm["shifts"]
        if any(shift_slots[s] for s in shift_slots):
            scheduled_today += 1
        due_in_shift += len(shift_slots.get(cur_shift) or [])
    labs_pending = 0
    for lab in (labs or []):
        if (lab.get("status") or "").lower() in ("ordered", "pending",
                                                    "in_lab", "resulting"):
            labs_pending += 1
    return {
        "med_count":             len(meds),
        "scheduled_today":       scheduled_today,
        "continuous_count":      continuous_count,
        "prn_count":             prn_count,
        "due_in_current_shift":  due_in_shift,
        "current_shift":         cur_shift,
        "labs_pending":          labs_pending,
    }


def patients_for_picker(*, control_room_mod: Any,
                         control_session_mod: Any
                         ) -> list[dict[str, Any]]:
    """Build the picker list for the Medical Records entry page.

    Returns one entry per patient persona across the room (multi-
    patient) OR the active singleton session (v6). Each entry:
      { encounter_id, encounter_label, character_id, name, mrn,
        status: {patient_status output} }

    Caller passes the control_room + control_session modules to avoid
    import cycles.
    """
    from portal import ehr_seed as _ehr_seed
    out: list[dict[str, Any]] = []
    encounters: list[Any] = []
    room = control_room_mod.get_active_room()
    if room is not None and room.encounters:
        encounters = list(room.encounters.values())
    else:
        sess = control_session_mod.get_active()
        if sess is not None:
            encounters = [sess]
    for enc in encounters:
        # Patient-only seed (M58) so we don't pull family / clinician
        # personas into the medical record's patient picker.
        per_enc = _ehr_seed.seeds_for_patient_only(
            enc, ehr_id=getattr(enc, "ehr_id", None)) or []
        for p in per_enc:
            meds = p.get("medications") or []
            status = patient_status(meds, labs=None)
            out.append({
                "encounter_id":    getattr(enc, "id", ""),
                "encounter_label": (
                    getattr(enc, "encounter_label", None)
                    or getattr(enc, "scenario_name", "")
                    or ""
                ),
                "character_id":    p.get("character_id") or "",
                "name":            p.get("name") or "",
                "mrn":             p.get("mrn") or "",
                "location_label":  p.get("location_label") or "",
                "status":          status,
            })
    return out
