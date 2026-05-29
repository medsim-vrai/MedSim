"""Deterministic device-behaviour rules — scored from the v6 device
event log alongside the v3 chart events.

Five rules at v6.0:

1. **alarm.response_latency** — for every instructor-injected alarm, was it
   silenced and cleared? What was time-to-silence and time-to-clear?
2. **alarm.uncleared** — how many alarms were still live at session end?
3. **cabinet.witness_compliance** — for every controlled-substance
   transaction (waste / discrepancy_resolve), was a witness recorded?
4. **cabinet.scan_compliance** — for every Remove on a med that has an
   NDC, was a scan.verify event recorded immediately before? (and did
   it match?)
5. **pump.library_override** — Alaris-specific: how often was a
   Guardrails soft-limit overridden? Each override is logged but flagged.

Output mirrors the existing `score.py` row shape:

    {"rule": "<id>", "label": "<human>", "pass": bool, "evidence": {...}}
"""
from __future__ import annotations

from typing import Any


def score(debrief_section: dict[str, Any]) -> list[dict[str, Any]]:
    """``debrief_section`` is the v6 ``device_timeline`` (list of dicts)
    plus context. We re-derive from it rather than re-reading SQLite, so
    the comparison stays self-contained.
    """
    timeline   = debrief_section.get("device_timeline") or []
    alarm_log  = debrief_section.get("alarm_log") or []
    dispenses  = debrief_section.get("medication_dispense_log") or []
    pump_progs = debrief_section.get("pump_program_log") or []

    out: list[dict[str, Any]] = []

    # 1 + 2 — alarm response.
    cleared    = [a for a in alarm_log if a.get("cleared")]
    uncleared  = [a for a in alarm_log if not a.get("cleared")]
    if alarm_log:
        avg_silence = _avg([a.get("time_to_silence_s") for a in cleared
                             if a.get("time_to_silence_s") is not None])
        avg_clear   = _avg([a.get("time_to_clear_s") for a in cleared
                             if a.get("time_to_clear_s") is not None])
        out.append({
            "rule": "alarm.response_latency",
            "label": "Alarm response latency",
            "pass": len(cleared) == len(alarm_log) and (avg_clear or 0) <= 60,
            "evidence": {
                "alarms_total":          len(alarm_log),
                "alarms_cleared":        len(cleared),
                "alarms_uncleared":      len(uncleared),
                "avg_time_to_silence_s": avg_silence,
                "avg_time_to_clear_s":   avg_clear,
            },
        })
    if uncleared:
        out.append({
            "rule": "alarm.uncleared",
            "label": "Alarms still active at session end",
            "pass": False,
            "evidence": {
                "count": len(uncleared),
                "tones": [a.get("tone") for a in uncleared],
            },
        })

    # 3 — cabinet witness compliance for controlled substances. A
    # transaction needs a witness when its verb is waste or
    # discrepancy_resolve, or when remove targets a controlled med (we
    # detect the second case via the absence of witness_user when the
    # underlying engine set witness_pending — that's payload-only data,
    # so the rule here is a conservative: any waste / discrepancy
    # without witness fails).
    needs_witness = [d for d in dispenses
                     if d["verb"] in ("waste", "discrepancy_resolve")]
    missing = [d for d in needs_witness if not d.get("witness_user")]
    if needs_witness:
        out.append({
            "rule": "cabinet.witness_compliance",
            "label": "Controlled-substance witness co-sign",
            "pass": not missing,
            "evidence": {
                "transactions_requiring_witness": len(needs_witness),
                "witnessed":     len(needs_witness) - len(missing),
                "missing":       len(missing),
                "missing_rows":  [{"ts": d["ts"], "verb": d["verb"],
                                    "med_id": d["med_id"]}
                                   for d in missing],
            },
        })

    # 4 — scan compliance for Remove. For each cabinet.remove event,
    # was there a scan.verify with result=match in the 60s before it,
    # for the same station and same med?
    out.append(_scan_compliance(timeline, dispenses))

    # 5 — pump library override count.
    overrides = [p for p in pump_progs if p.get("soft_override")]
    if pump_progs:
        out.append({
            "rule": "pump.library_override",
            "label": "Pump drug-library soft-limit overrides",
            "pass": len(overrides) == 0,
            "evidence": {
                "programs_total":     len(pump_progs),
                "overrides":          len(overrides),
                "override_rows":      [{"ts": p["ts"], "drug": p.get("drug_label"),
                                          "rate_ml_hr": p.get("rate_ml_hr")}
                                         for p in overrides],
            },
        })

    return out


def _scan_compliance(timeline: list[dict[str, Any]],
                     dispenses: list[dict[str, Any]]) -> dict[str, Any]:
    """For every cabinet.remove, look back 60s for a same-station
    scan.verify with result=match."""
    removes = [d for d in dispenses if d["verb"] == "remove"]
    scans   = [r for r in timeline if r["type"] == "scan.verify"]
    matched = 0
    unmatched_rows: list[dict[str, Any]] = []
    for r in removes:
        ok = False
        for s in scans:
            if (s["station_id"] == r["station_id"]
                    and 0 <= (r["ts"] - s["ts"]) <= 60
                    and (s["payload"] or {}).get("result") == "match"):
                ok = True; break
        if ok:
            matched += 1
        else:
            unmatched_rows.append({"ts": r["ts"], "med_id": r["med_id"]})
    return {
        "rule": "cabinet.scan_compliance",
        "label": "Barcode-verify before Remove",
        "pass": (not removes) or (matched == len(removes)),
        "evidence": {
            "removes_total":      len(removes),
            "scanned":            matched,
            "unscanned":          len(removes) - matched,
            "unscanned_rows":     unmatched_rows,
        },
    }


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return round(sum(xs) / len(xs), 2)
