"""Debrief builder for MEDSIM 2.

Builds a structured debrief from a ControlSession's transcript:

  - per-turn NCJMM tagging (via portal/ncjmm.py — ported from Voice4MedSim_v6)
  - summary stats (turn counts, durations, latencies)
  - role-group + safety-class distributions
  - per-persona engagement
  - curriculum-objective alignment — for each module selected in the wizard,
    scan the transcript for evidence of medications / procedures / treatments /
    red flags / devices / conditions

The result is saved as JSON to data/debriefs/<session_id>.json on session end
so it survives server restarts and can be reviewed/exported later.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path
from typing import Any

from . import control_session, ehr_db, library, ncjmm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEBRIEFS_DIR = PROJECT_ROOT / "data" / "debriefs"

OBJECTIVE_CATEGORIES = (
    ("conditions",         "Conditions"),
    ("medications",        "Medications"),
    ("devices",            "Devices"),
    ("procedures",         "Procedures"),
    ("primaryTreatments",  "Primary treatments"),
    ("alternateTreatments","Alternate treatments"),
    ("redFlags",           "Red flags"),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _staged_errors_section(sess: control_session.ControlSession) -> list[dict[str, Any]]:
    """FR-008 S6 — the staged-error arc for the debrief: what was planted, where,
    whether it fired, and whether the student caught it. Times are wall-clock
    strings (HH:MM) so the template stays dumb. Empty list when nothing staged."""
    try:
        from portal import med_errors
    except Exception:  # noqa: BLE001
        return []

    def hm(ts: float | None) -> str | None:
        return time.strftime("%H:%M", time.localtime(ts)) if ts else None

    out: list[dict[str, Any]] = []
    for rec in med_errors.state(sess.id).get("errors", []):
        imp = rec.get("impact") or {}
        ist = rec.get("impact_state") or {}
        out.append({
            "id": rec["id"],
            "type_display": med_errors.TYPE_DISPLAY.get(rec["type"], rec["type"]),
            "vector_display": med_errors.VECTOR_DISPLAY.get(rec["vector"], rec["vector"]),
            "encounter_display": med_errors.ENCOUNTER_DISPLAY_SHORT.get(
                rec["encounter"], rec["encounter"]),
            "display": rec["payload"].get("display", ""),
            "status": rec["status"],
            "outcome": rec.get("outcome"),
            "note": rec.get("note") or "",
            "armed_at": hm(rec.get("armed_at")),
            "delivered_at": hm(rec.get("delivered_at")),
            "triggered_at": hm(rec.get("triggered_at")),
            "resolved_at": hm(rec.get("resolved_at")),
            "impact": ({
                "profile": imp.get("profile"), "severity": imp.get("severity"),
                "trigger": imp.get("trigger"),
                "stabilized_at": hm(ist.get("stabilized_at")),
            } if imp else None),
        })
    return out


def build(sess: control_session.ControlSession) -> dict[str, Any]:
    """Build a complete debrief dict from a live or recently-active session."""
    entries = sess.transcript
    started = sess.started_at
    ended = time.time()
    duration_s = max(0, int(ended - started))

    # Pair student+character turns to compute NCJMM tag per round-trip.
    paired_turns = _pair_turns(entries)
    for p in paired_turns:
        p["ncjmm_step"] = ncjmm.tag(p["student_text"], p["character_text"])

    # Per-entry: also tag every transcript entry (for the per-turn renderer)
    tagged_entries = _tag_entries(entries, paired_turns)

    summary = _summary(entries, paired_turns, duration_s)
    ncjmm_coverage = _ncjmm_coverage(paired_turns)
    role_groups = _role_group_distribution(paired_turns)
    safety_classes = _safety_class_distribution(paired_turns)
    personas_engagement = _personas_engagement(sess, paired_turns)
    objective_alignment = _objective_alignment(entries, sess.selected_modules)

    # V3 — Documentation + Orders alignment cards (Blueprint §13).
    documentation_alignment = _documentation_alignment(sess, started)
    orders_alignment        = _orders_alignment(sess, paired_turns)

    # V6 — Device sections (pump + cabinet activity merged into the timeline).
    device_sections = _device_sections(sess, started, ended)

    # FR-008 S6 — the staged-medication-error arc (empty list when none staged).
    staged_errors = _staged_errors_section(sess)

    return {
        "session_id":        sess.id,
        "join_code":         sess.join_code,
        "scenario_name":     sess.scenario_name,
        "scenario_notes":    sess.scenario_notes,
        "scenario_text":     sess.scenario_text,
        "program_id":        sess.program_id,
        "week":              sess.week,
        "selected_modules":  list(sess.selected_modules),
        "selected_personas": list(sess.selected_personas),
        "stations":          [
            {
                "station_id": st.station_id,
                "persona_id": st.persona_id,
                "joined_at":  st.joined_at,
                "turns":      len(st.history),
                "user_agent": st.user_agent,
            }
            for st in sess.stations.values()
        ],
        "started_at":        started,
        "ended_at":          ended,
        "duration_seconds":  duration_s,
        "summary":           summary,
        "ncjmm_coverage":    ncjmm_coverage,
        "role_group_distribution":   role_groups,
        "safety_class_distribution": safety_classes,
        "personas_engagement":       personas_engagement,
        "objective_alignment":       objective_alignment,
        "documentation_alignment":   documentation_alignment,
        "orders_alignment":          orders_alignment,
        "staged_errors":             staged_errors,
        "ehr_id":                    getattr(sess, "ehr_id", None),
        "charting_locked_at":        getattr(sess, "charting_locked_at", None),
        "transcript":                tagged_entries,
        # V6 device subsystem sections — empty if no devices joined.
        "devices":                   device_sections["devices"],
        "device_timeline":           device_sections["timeline"],
        "alarm_log":                 device_sections["alarms"],
        "medication_dispense_log":   device_sections["dispenses"],
        "pump_program_log":          device_sections["pump_programs"],
        "_meta": {
            "generated_at": ended,
            "generator":    "medsim6.debrief v1",
        },
    }


def _device_sections(sess: control_session.ControlSession, started: float,
                      ended: float) -> dict[str, Any]:
    """Build the four V6 device-subsystem debrief sections from the
    append-only device_event log and device_assignment history."""
    from . import ehr_db

    out_devices: list[dict[str, Any]] = []
    out_timeline: list[dict[str, Any]] = []
    out_alarms: list[dict[str, Any]] = []
    out_dispenses: list[dict[str, Any]] = []
    out_pump_programs: list[dict[str, Any]] = []

    device_stations = getattr(sess, "device_stations", {}) or {}

    for sid, ds in device_stations.items():
        events = ehr_db.device_events(station_id=sid)
        history = ehr_db.assignment_history(sid)
        out_devices.append({
            "station_id":   sid,
            "device_kind":  ds.device_kind,
            "device_model": ds.device_model,
            "label":        ds.label,
            "joined_at":    ds.joined_at,
            "event_count":  len(events),
            "assignment_history": history,
        })

        # Track open alarms so we can compute time-to-silence and
        # time-to-clear once we see the matching silenced/cleared event.
        open_alarms: dict[str, dict[str, Any]] = {}

        for ev in events:
            payload = ev.get("payload", {}) or {}
            t = ev["type"]
            row = {
                "ts":           ev["ts"],
                "station_id":   sid,
                "device_kind":  ds.device_kind,
                "device_model": ds.device_model,
                "type":         t,
                "surface":      ev.get("surface"),
                "character_id": payload.get("character_id"),
                "payload":      payload,
            }
            out_timeline.append(row)

            if t == "alarm.injected":
                tone = payload.get("tone")
                if tone:
                    open_alarms[tone] = {
                        "tone": tone, "raised_at": ev["ts"],
                        "source": ev.get("surface"),
                        "auto":   bool(payload.get("auto")),
                    }
            elif t == "alarm.silenced":
                tone = payload.get("tone")
                if tone and tone in open_alarms:
                    open_alarms[tone]["silenced_at"] = ev["ts"]
                    open_alarms[tone]["time_to_silence_s"] = round(
                        ev["ts"] - open_alarms[tone]["raised_at"], 1)
            elif t == "alarm.cleared":
                tone = payload.get("tone")
                rec = open_alarms.pop(tone, None)
                if rec is not None:
                    rec["cleared_at"] = ev["ts"]
                    rec["time_to_clear_s"] = round(ev["ts"] - rec["raised_at"], 1)
                    rec["cleared"] = True
                    rec["station_id"]   = sid
                    rec["device_model"] = ds.device_model
                    rec["character_id"] = payload.get("character_id")
                    out_alarms.append(rec)
            elif t in ("cabinet.remove", "cabinet.return", "cabinet.waste",
                        "cabinet.override", "cabinet.discrepancy_resolve"):
                out_dispenses.append({
                    "ts":           ev["ts"],
                    "station_id":   sid,
                    "device_model": ds.device_model,
                    "verb":         t.split(".", 1)[-1],
                    "med_id":       payload.get("med_id"),
                    "qty":          payload.get("qty"),
                    "amount":       payload.get("amount"),
                    "patient":      payload.get("patient_id") or payload.get("character_id"),
                    "witness_user": payload.get("witness_user"),
                    "reason":       payload.get("reason"),
                })
            elif t in ("pump.program", "pump.start", "pump.rate_change",
                        "feed.program", "feed.start"):
                out_pump_programs.append({
                    "ts":           ev["ts"],
                    "station_id":   sid,
                    "device_kind":  ds.device_kind,
                    "device_model": ds.device_model,
                    "type":         t,
                    "channel":      payload.get("channel"),
                    "drug_code":    payload.get("drug_code"),
                    "drug_label":   payload.get("drug_label"),
                    "rate_ml_hr":   payload.get("rate_ml_hr"),
                    "vtbi_ml":      payload.get("vtbi_ml"),
                    "dose":         payload.get("dose"),
                    "dose_unit":    payload.get("dose_unit"),
                    "library_used":  payload.get("library_used"),
                    "soft_override": payload.get("soft_override"),
                    "character_id": payload.get("character_id"),
                })

        # Alarms still open at session end — record them as uncleared.
        for tone, rec in open_alarms.items():
            rec["cleared"] = False
            rec["station_id"]   = sid
            rec["device_model"] = ds.device_model
            out_alarms.append(rec)

    out_timeline.sort(key=lambda r: r["ts"])
    out_alarms.sort(key=lambda r: r["raised_at"])
    out_dispenses.sort(key=lambda r: r["ts"])
    out_pump_programs.sort(key=lambda r: r["ts"])

    return {
        "devices":        out_devices,
        "timeline":       out_timeline,
        "alarms":         out_alarms,
        "dispenses":      out_dispenses,
        "pump_programs":  out_pump_programs,
    }


def save(debrief: dict[str, Any]) -> Path:
    DEBRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBRIEFS_DIR / f"{debrief['session_id']}.json"
    path.write_text(json.dumps(debrief, indent=2, default=str))
    return path


def load(session_id: str) -> dict[str, Any] | None:
    path = DEBRIEFS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return _migrate_legacy(data)


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """Bring older debrief JSON shapes in line with the current template.

    v1 of this module used a key 'items' inside each category — which
    collides with Jinja's dict.items method-name lookup. Renamed to
    'all_items' and now also precompute 'unmatched'. Old saved files
    get patched on read so they don't 500 in the detail view.
    """
    for mod in data.get("objective_alignment", []) or []:
        cats = mod.get("categories") or {}
        for _key, cat in cats.items():
            if not isinstance(cat, dict):
                continue
            if "all_items" not in cat and "items" in cat:
                cat["all_items"] = cat.pop("items")
            if "unmatched" not in cat:
                all_items = cat.get("all_items") or []
                matches = cat.get("matches") or []
                cat["unmatched"] = [i for i in all_items if i not in matches]
    return data


def list_saved() -> list[dict[str, Any]]:
    if not DEBRIEFS_DIR.exists():
        return []
    out = []
    for path in sorted(DEBRIEFS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            out.append({
                "session_id":     data.get("session_id", path.stem),
                "scenario_name":  data.get("scenario_name", path.stem),
                "started_at":     data.get("started_at"),
                "ended_at":       data.get("ended_at"),
                "duration_seconds": data.get("duration_seconds", 0),
                "total_turns":    data.get("summary", {}).get("total_turns", 0),
                "personas_count": len(data.get("selected_personas", [])),
                "modules_count":  len(data.get("selected_modules", [])),
                "path":           str(path),
                "size_kb":        round(path.stat().st_size / 1024, 1),
            })
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _pair_turns(entries: list[control_session.TranscriptEntry]) -> list[dict[str, Any]]:
    """Pair consecutive student+character entries into a single round-trip.

    Transcript invariant (see control_session.log_turn): student then
    character, in pairs, ts strictly increasing. So a simple two-step walk
    suffices.
    """
    pairs: list[dict[str, Any]] = []
    i = 0
    while i < len(entries) - 1:
        a, b = entries[i], entries[i + 1]
        if a.direction == "student" and b.direction == "character" and a.persona_id == b.persona_id:
            pairs.append({
                "ts":              a.ts,
                "source":          a.source,
                "source_label":    a.source_label,
                "persona_id":      a.persona_id,
                "persona_name":    a.persona_name,
                "student_text":    a.text,
                "character_text":  b.text,
                "latency_ms":      b.latency_ms,
            })
            i += 2
        else:
            i += 1
    return pairs


def _tag_entries(entries, paired_turns):
    """Return a list[dict] of every transcript entry, with the NCJMM step
    from the corresponding pair attached to BOTH the student and character
    entries of that round-trip."""
    # Build a lookup: ts (rounded) → ncjmm_step
    by_ts = {round(p["ts"], 2): p["ncjmm_step"] for p in paired_turns}
    out = []
    for e in entries:
        step = by_ts.get(round(e.ts, 2)) or by_ts.get(round(e.ts - 0.001, 2))
        out.append({
            "ts":            e.ts,
            "source":        e.source,
            "source_label":  e.source_label,
            "persona_id":    e.persona_id,
            "persona_name":  e.persona_name,
            "direction":     e.direction,
            "text":          e.text,
            "latency_ms":    e.latency_ms,
            "ncjmm_step":    step,
        })
    return out


def _summary(entries, paired_turns, duration_s):
    student = sum(1 for e in entries if e.direction == "student")
    character = sum(1 for e in entries if e.direction == "character")
    station_turns = sum(1 for p in paired_turns if p["source"].startswith("station:"))
    operator_turns = sum(1 for p in paired_turns if p["source"] == "operator")
    unique_personas = len({p["persona_id"] for p in paired_turns})

    latencies = [p["latency_ms"] for p in paired_turns if p.get("latency_ms")]
    lat_mean = int(statistics.mean(latencies)) if latencies else None
    lat_p95 = int(_percentile(latencies, 0.95)) if latencies else None
    lat_p50 = int(_percentile(latencies, 0.50)) if latencies else None
    lat_max = int(max(latencies)) if latencies else None

    return {
        "total_turns":      len(entries),
        "round_trips":      len(paired_turns),
        "student_turns":    student,
        "character_turns":  character,
        "station_turns":    station_turns,
        "operator_turns":   operator_turns,
        "personas_engaged": unique_personas,
        "duration_seconds": duration_s,
        "duration_pretty":  _fmt_duration(duration_s),
        "latency_p50_ms":   lat_p50,
        "latency_mean_ms":  lat_mean,
        "latency_p95_ms":   lat_p95,
        "latency_max_ms":   lat_max,
    }


def _ncjmm_coverage(paired_turns):
    counts = {step: 0 for step in ncjmm.NCJMM_STEPS}
    for p in paired_turns:
        step = p.get("ncjmm_step")
        if step in counts:
            counts[step] += 1
    return counts


def _role_group_distribution(paired_turns):
    counts = {"Clinician": 0, "Allied Health": 0, "Patient": 0, "Family": 0}
    for p in paired_turns:
        persona = library.get_persona(p["persona_id"])
        if persona:
            rg = persona.get("roleGroup")
            if rg in counts:
                counts[rg] += 1
    return counts


def _safety_class_distribution(paired_turns):
    counts = {"baseline": 0, "sensitive": 0, "high-risk": 0}
    for p in paired_turns:
        persona = library.get_persona(p["persona_id"])
        if persona:
            sc = persona.get("safetyClass", "baseline")
            if sc in counts:
                counts[sc] += 1
    return counts


def _personas_engagement(sess, paired_turns):
    out = []
    by_pid: dict[str, list[dict[str, Any]]] = {}
    for p in paired_turns:
        by_pid.setdefault(p["persona_id"], []).append(p)
    for pid in sess.selected_personas:
        persona = library.get_persona(pid)
        if not persona:
            continue
        turns = by_pid.get(pid, [])
        lats = [p["latency_ms"] for p in turns if p.get("latency_ms")]
        out.append({
            "id":            pid,
            "name":          persona.get("name", pid),
            "role":          persona.get("role", ""),
            "role_group":    persona.get("roleGroup", ""),
            "safety_class":  persona.get("safetyClass", "baseline"),
            "altered_state": persona.get("alteredState"),
            "turns":         len(turns),
            "avg_latency_ms": int(statistics.mean(lats)) if lats else None,
            "engaged":       bool(turns),
        })
    # Sort: most turns first
    out.sort(key=lambda r: r["turns"], reverse=True)
    return out


def _objective_alignment(entries, selected_module_ids):
    """For each module selected in the wizard, scan transcript text for
    evidence of medications, procedures, treatments, red flags, devices,
    conditions. Returns N/M coverage per category."""
    all_text = " ".join(e.text for e in entries).lower()
    out = []
    for mid in selected_module_ids:
        module = library.get_module(mid)
        if not module:
            continue
        cats: dict[str, dict[str, Any]] = {}
        total_items = 0
        total_matched = 0
        for cat_key, cat_label in OBJECTIVE_CATEGORIES:
            items = module.get(cat_key, []) or []
            matches: list[str] = []
            for item in items:
                for term in _extract_search_terms(item, cat_key):
                    if term and term.lower() in all_text:
                        matches.append(item)
                        break
            unmatched = [it for it in items if it not in matches]
            cats[cat_key] = {
                "label":     cat_label,
                "total":     len(items),
                "matched":   len(matches),
                "matches":   matches,
                "all_items": items,       # renamed from "items" to avoid Jinja
                                          # dict.items() method-name collision
                "unmatched": unmatched,   # precomputed for the template
            }
            total_items += len(items)
            total_matched += len(matches)
        out.append({
            "module_id":         mid,
            "module_title":      module.get("title", mid),
            "nclex_domain":      module.get("nclexDomain", ""),
            "summary":           module.get("summary", ""),
            "categories":        cats,
            "total_items":       total_items,
            "total_matched":     total_matched,
            "coverage_percent":  int(100 * total_matched / total_items) if total_items else 0,
            "role_hooks":        module.get("roleHooks", {}),
            "scope_of_practice": module.get("scopeOfPractice", {}),
        })
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_search_terms(item: str, category: str) -> list[str]:
    """Extract substring search candidates from a module item. For drug lists
    we split on commas; for procedures/treatments we take the phrase before
    a colon or parenthesis."""
    if not item:
        return []
    item = item.strip()
    if category == "medications":
        parts = re.split(r"[,;:()/]", item)
        return [p.strip() for p in parts if 3 <= len(p.strip()) <= 50]
    s = re.split(r"[:(]", item, maxsplit=1)[0].strip()
    if 3 <= len(s) <= 80:
        return [s]
    if s:
        return [s[:80]]
    return []


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    if f == c:
        return sorted_vals[f]
    d = k - f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * d


def _fmt_duration(s: int) -> str:
    if s < 60:
        return f"{s}s"
    m, ss = divmod(s, 60)
    if m < 60:
        return f"{m}m {ss}s"
    h, mm = divmod(m, 60)
    return f"{h}h {mm}m"


# ---------------------------------------------------------------------------
# V3 — Documentation + Orders alignment (Blueprint §13)
# ---------------------------------------------------------------------------

_RED_FLAG_PATTERNS = {
    "hypotension":        re.compile(r"\b(?:hypotensi(?:on|ve)|map\s*<\s*65|bp\s*\d{2}/\d{2})\b", re.I),
    "tachycardia":        re.compile(r"\b(?:tachycardi[ac]|hr\s*>\s*120)\b", re.I),
    "hypoxia":            re.compile(r"\b(?:hypox(?:ia|emi[ac])|spo2\s*<\s*9[0-2])\b", re.I),
    "altered mental status": re.compile(r"\b(?:altered ms|amsa|confused|disoriented|cam positive)\b", re.I),
    "respiratory depression": re.compile(r"\b(?:rr\s*<\s*10|respiratory depression|sedation)\b", re.I),
    "chest pain":         re.compile(r"\bchest pain\b", re.I),
    "bleeding":           re.compile(r"\b(?:bleeding|hemorrhage|hematemesis|melena)\b", re.I),
}


def _documentation_alignment(sess, started_at: float) -> dict[str, Any]:
    """Pull the comparison report (if it exists) and decorate it with
    per-note metadata: word count, signed-at timestamp, time-to-first-note
    measured from scenario start.
    """
    report = ehr_db.get_comparison(sess.id) or {}
    rules = report.get("rules") or {}
    rubric = report.get("rubric") or {}

    events = ehr_db.events(sess.id)
    note_events = [e for e in events if e.get("type") == "note.save"]
    # Latest write wins per note_id for the metadata roll-up.
    notes_by_id: dict[str, dict[str, Any]] = {}
    for ev in note_events:
        p = ev.get("payload") or {}
        nid = p.get("note_id") or f"n_{ev['ts']}"
        notes_by_id[nid] = {
            "id":         nid,
            "type":       p.get("note_type", "Note"),
            "words":      len((p.get("body") or "").split()),
            "signed":     bool(p.get("signed")),
            "signed_at":  ev["ts"] if p.get("signed") else None,
            "ttf_first_s": int(ev["ts"] - started_at) if ev["ts"] > started_at else 0,
        }
    notes_meta = list(notes_by_id.values())
    notes_meta.sort(key=lambda n: n.get("signed_at") or n.get("ttf_first_s") or 0)

    return {
        "available":    bool(report),
        "composite":    report.get("score", 0.0),
        "model":        report.get("model"),
        "built_at":     report.get("built_at"),
        "rubric":       rubric,
        "rules":        {
            "hits":         rules.get("hits", []),
            "misses":       rules.get("misses", []),
            "speculative":  rules.get("speculative", []),
            "by_module":    rules.get("by_module", []),
            "totals":       rules.get("totals", {}),
        },
        "notes_meta":   notes_meta,
        "note_count":   len(notes_meta),
        "signed_count": sum(1 for n in notes_meta if n["signed"]),
    }


def _orders_alignment(sess, paired_turns: list[dict[str, Any]]) -> dict[str, Any]:
    orders = ehr_db.orders(sess.id)
    by_category: dict[str, int] = {}
    rationale_substantive = 0
    priority_dist = {"routine": 0, "stat": 0, "now": 0}
    for o in orders:
        order = o.get("order") or {}
        cat = order.get("category", "?")
        by_category[cat] = by_category.get(cat, 0) + 1
        if len((order.get("rationale") or "").split()) >= 4:
            rationale_substantive += 1
        pri = order.get("priority", "routine")
        if pri in priority_dist:
            priority_dist[pri] += 1

    # Trigger-latency: for each red flag that surfaced in the transcript,
    # how long after that turn did the first order land?
    trigger_latency: list[dict[str, Any]] = []
    first_seen_at: dict[str, float] = {}
    for p in paired_turns:
        text = (p.get("student_text", "") + " " + p.get("character_text", "")).lower()
        for flag, pattern in _RED_FLAG_PATTERNS.items():
            if flag in first_seen_at:
                continue
            if pattern.search(text):
                first_seen_at[flag] = p["ts"]
    for flag, t0 in first_seen_at.items():
        next_order = next((o for o in orders if o.get("ts", 0) >= t0), None)
        if next_order:
            trigger_latency.append({
                "flag":          flag,
                "first_order_s": int(next_order["ts"] - t0),
            })
        else:
            trigger_latency.append({"flag": flag, "first_order_s": None})

    return {
        "total_orders":      len(orders),
        "by_category":       by_category,
        "priority_dist":     priority_dist,
        "rationale_quality": round(rationale_substantive / len(orders), 3) if orders else 0.0,
        "trigger_latency_s": trigger_latency,
    }


# ─────────────────────────────────────────────────────────────────────
# V7 — Cohort debrief (M14)
#
# `build_cohort_debrief(room)` aggregates every encounter's per-encounter
# debrief into one PEARLS-scaffolded JSON. PEARLS — Promoting Excellence
# And Reflective Learning in Simulation (Eppich & Cheng 2015) — has
# four phases:
#   1. Reactions   — "how did this go for you?" — student-led
#   2. Description — what happened, sequencing of events
#   3. Analysis    — gaps, performance frames, what surprised you
#   4. Application — takeaway commitments + planned actions
# Plus a brief Summary.
#
# The cohort debrief presents room-level aggregates alongside per-
# encounter facets so the instructor can run one debrief covering
# every student's run. M15 will render this as a web page; M14 is
# data-layer only.
# ─────────────────────────────────────────────────────────────────────

COHORT_DEBRIEFS_DIR = DEBRIEFS_DIR / "cohort"


def build_cohort_debrief(room: Any) -> dict[str, Any]:
    """Aggregate every encounter in ``room`` into a cohort debrief.

    ``room`` is a ``control_room.ControlRoom``. Callers fire this
    BEFORE the room's singleton is cleared (the M15 route in M15 will
    own the lifecycle). Returns a PEARLS-scaffolded JSON dict ready
    for render or save.

    Robust to encounters with no transcript / no chart events — they
    appear in the aggregate with zeroed metrics. Robust to clones
    (M13): each clone is its own encounter and gets its own facet.
    """
    encounters = list(room.encounters.values())
    facets: list[dict[str, Any]] = []
    for enc in encounters:
        try:
            facet = build(enc)
        except Exception as exc:  # noqa: BLE001 — keep aggregate going
            facet = {
                "session_id":    enc.id,
                "join_code":     enc.join_code,
                "scenario_name": enc.scenario_name,
                "_error":        f"per-encounter debrief build failed: {exc}",
                "duration_seconds": 0,
                "summary":       {},
                "transcript":    [],
                "stations":      [],
            }
        # M30 — surface lead_student per facet so M15's renderer can
        # show "Bed 3 (lead: Alice Pham)" in the per-encounter tab.
        facet["lead_student_id"] = enc.lead_student_id
        if (enc.lead_student_id
                and getattr(room, "students", None)
                and enc.lead_student_id in room.students):
            facet["lead_student_name"] = room.students[enc.lead_student_id].display_name
        else:
            facet["lead_student_name"] = None
        # M30 — encounter_label so the cohort UI can show whatever the
        # operator labeled the bed (e.g. "Bed 3 — Kowalski") even when
        # scenario_name and label drift apart.
        facet["encounter_label"] = enc.encounter_label or enc.scenario_name
        facets.append(facet)
    # ── Cohort-level aggregates ──
    n_encounters = len(facets)
    n_students   = len(getattr(room, "students", {}) or {})
    total_chat_turns = 0
    total_chart_events = 0
    total_duration = 0
    persona_engagement: dict[str, int] = {}
    for f in facets:
        summary = f.get("summary") or {}
        total_chat_turns   += int(summary.get("total_turns", 0) or 0)
        total_duration     += int(f.get("duration_seconds") or 0)
        # chart_event count via len(transcript) is wrong; we use the
        # ehr_db log directly for accuracy. Fall back to 0 on missing
        # session_id.
        sid = f.get("session_id")
        if sid:
            total_chart_events += len(ehr_db.events(sid))
        # Persona engagement across the cohort.
        for pe in f.get("personas_engagement", []) or []:
            pid = pe.get("persona_id")
            if pid:
                persona_engagement[pid] = (
                    persona_engagement.get(pid, 0) +
                    int(pe.get("turn_count", 0) or 0)
                )

    avg_duration_per_encounter = (
        total_duration / n_encounters if n_encounters else 0
    )
    avg_turns_per_encounter = (
        total_chat_turns / n_encounters if n_encounters else 0
    )

    # ── Persona engagement ranked ──
    persona_engagement_ranked = sorted(
        ({"persona_id": pid, "turn_count": n}
          for pid, n in persona_engagement.items()),
        key=lambda r: -r["turn_count"],
    )

    # ── PEARLS scaffold ──
    # Each section is mostly empty (the instructor fills it during
    # the live debrief), but we pre-populate Description from the
    # cohort facts and Analysis-grade hints with the metrics that
    # would normally fuel that phase of the discussion.
    pearls = {
        "reactions":   {
            "prompt": "How did this run go for each of you?",
            "notes":  "",  # instructor fills live
        },
        "description": {
            "prompt": "Let's walk through what happened.",
            "facts": [
                f"{n_encounters} encounter{'s' if n_encounters != 1 else ''} "
                f"with {n_students} student{'s' if n_students != 1 else ''} "
                f"total.",
                f"Average duration per encounter: "
                f"{_fmt_duration(int(avg_duration_per_encounter))}.",
                f"Total chat turns across cohort: {total_chat_turns}.",
                f"Total chart events across cohort: {total_chart_events}.",
            ],
        },
        "analysis":    {
            "prompt": "What did you notice? What surprised you?",
            "performance_frames": [
                # Per-encounter NCJMM coverage at a glance.
                {
                    "session_id":   f.get("session_id"),
                    "scenario_name": f.get("scenario_name"),
                    "ncjmm_coverage": f.get("ncjmm_coverage", {}),
                    "duration_seconds": f.get("duration_seconds", 0),
                    "turns":         (f.get("summary") or {}).get("total_turns", 0),
                }
                for f in facets
            ],
            "persona_engagement_ranked": persona_engagement_ranked,
        },
        "application": {
            "prompt": "What will you do differently next shift?",
            "commitments": [],
        },
        "summary": {
            "encounters_count":    n_encounters,
            "students_count":      n_students,
            "total_chat_turns":    total_chat_turns,
            "total_chart_events":  total_chart_events,
            "total_duration_seconds": total_duration,
            "avg_duration_per_encounter_seconds": avg_duration_per_encounter,
            "avg_turns_per_encounter":            avg_turns_per_encounter,
        },
    }

    return {
        "room_id":      room.room_id,
        "room_code":    room.room_code,
        "room_label":   room.label or "",
        "room_status":  room.status,
        "encounters":   facets,
        "pearls":       pearls,
        "_meta": {
            "generated_at": time.time(),
            "generator":    "medsim7.debrief.cohort v1",
        },
    }


def save_cohort(debrief: dict[str, Any]) -> Path:
    """Persist a cohort debrief to ``data/debriefs/cohort/<room_id>.json``."""
    COHORT_DEBRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    path = COHORT_DEBRIEFS_DIR / f"{debrief['room_id']}.json"
    path.write_text(json.dumps(debrief, indent=2, default=str))
    return path


def load_cohort(room_id: str) -> dict[str, Any] | None:
    path = COHORT_DEBRIEFS_DIR / f"{room_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def list_saved_cohorts() -> list[dict[str, Any]]:
    """Lightweight index of saved cohort debriefs (room_id + room_label
    + generated_at). For an eventual cohort-debrief index page."""
    if not COHORT_DEBRIEFS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(COHORT_DEBRIEFS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        out.append({
            "room_id":      data.get("room_id"),
            "room_code":    data.get("room_code"),
            "room_label":   data.get("room_label"),
            "encounters_count": (data.get("pearls") or {})
                                  .get("summary", {})
                                  .get("encounters_count", 0),
            "generated_at": (data.get("_meta") or {}).get("generated_at"),
        })
    # Newest first.
    out.sort(key=lambda r: -(r.get("generated_at") or 0))
    return out
