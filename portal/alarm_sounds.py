"""Clinical-alarm audio asset library (M49).

Maps an alarm dict (the same shape `alarms.active_alarms()` emits)
to an `audio_url` pointing at one of the 15 WAV files in
``portal/static/sounds/clinical_alarms/``.

Severity → priority bucket:
    critical → high
    warning  → medium
    info     → low

Source/metric → file family:
    threshold + hr      → hr_<priority>
    threshold + spo2    → spo2_<priority>
    threshold + rr      → rr_<priority>
    threshold + rhythm  → ecg_<priority>
    scene    + code.blue→ code_blue (no priority — single asset)
    device   + bed_alarm    family → bed_exit
    device   + call_bell    family → call_bell
    everything else → None (no sound — UI still flashes the visual badge)

The mapping is intentionally permissive: if a future alarm source
doesn't have a curated sound, `audio_url` returns None and the
nursing station's poll loop silently skips audio for that alarm.
The visual badge in the alarm board renders independent of audio.
"""
from __future__ import annotations

from typing import Any

# ────────────────────────────────────────────────────────────────────
# Asset library
# ────────────────────────────────────────────────────────────────────

_BASE = "/static/sounds/clinical_alarms"

# Per-metric file family keyed by priority bucket.
_METRIC_FILES: dict[str, dict[str, str]] = {
    "hr": {
        "high":   f"{_BASE}/05_nurses_station_hr_high_priority.wav",
        "medium": f"{_BASE}/09_nurses_station_hr_medium_priority.wav",
        "low":    f"{_BASE}/13_nurses_station_hr_low_priority.wav",
    },
    "spo2": {
        "high":   f"{_BASE}/06_nurses_station_spo2_high_priority.wav",
        "medium": f"{_BASE}/10_nurses_station_spo2_medium_priority.wav",
        "low":    f"{_BASE}/14_nurses_station_spo2_low_priority.wav",
    },
    "rr": {
        "high":   f"{_BASE}/07_nurses_station_rr_high_priority.wav",
        "medium": f"{_BASE}/11_nurses_station_rr_medium_priority.wav",
        "low":    f"{_BASE}/15_nurses_station_rr_low_priority.wav",
    },
    "ecg": {   # ECG / rhythm-breach
        "high":   f"{_BASE}/04_nurses_station_ecg_high_priority.wav",
        "medium": f"{_BASE}/08_nurses_station_ecg_medium_priority.wav",
        "low":    f"{_BASE}/12_nurses_station_ecg_low_priority.wav",
    },
}

# Single-priority special alarms — same WAV at any severity.
_SPECIAL_FILES: dict[str, str] = {
    "code_blue": f"{_BASE}/03_code_blue.wav",
    "bed_exit":  f"{_BASE}/01_bed_exit_alarm.wav",
    "call_bell": f"{_BASE}/02_call_bell.wav",
}


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────

def severity_to_priority(severity: str) -> str:
    """Map alarm severity → audio-library priority bucket.

    M50 — `danger` (dangerous waveforms) also maps to high priority,
    sharing the HIGH-priority audio bucket with `critical` since
    there's no distinct DANGER-priority WAV in the asset library.
    The DIFFERENCE between danger and critical is in the alarm board
    sort order (danger wins) — but they share the same audio cue.
    """
    if severity in ("danger", "critical"):
        return "high"
    if severity == "warning":
        return "medium"
    return "low"


def audio_url_for(alarm: dict[str, Any]) -> str | None:
    """Pick the right WAV for an alarm dict (or None if no curated
    sound matches). Reads `source`, `metric`, `kind`, and `severity`."""
    severity = (alarm.get("severity") or "").lower()
    source   = (alarm.get("source") or "").lower()
    metric   = (alarm.get("metric") or "").lower()
    kind     = (alarm.get("kind") or "").lower()
    priority = severity_to_priority(severity)

    # M48 threshold alarms — match by metric.
    if source == "threshold":
        family = metric
        if family == "rhythm":
            family = "ecg"
        # M50 — BP systolic + diastolic both ride the HR audio family
        # (the asset library doesn't ship a dedicated BP WAV; using
        # HR's bucket keeps the priority semantics intact).
        if family in ("bp_systolic", "bp_diastolic"):
            family = "hr"
        family_map = _METRIC_FILES.get(family)
        if family_map:
            return family_map.get(priority)

    # M7 scene alarms — match by scene kind.
    if source == "scene":
        if "code.blue" in kind or "code_blue" in kind:
            return _SPECIAL_FILES["code_blue"]
        # Vitals-related scenes drift toward the metric family.
        if "vitals.drop" in kind:
            # vitals.drop usually wedges HR/BP/SpO2 — default to HR
            # family at the alarm's severity.
            return _METRIC_FILES["hr"].get(priority)
        if "pump.alarm" in kind:
            return None   # pump alarms use the device's own audio
        return None

    # Device-source alarms — match by kind.
    if source == "device":
        if "call_bell" in kind:
            return _SPECIAL_FILES["call_bell"]
        if "bed_alarm" in kind or "bed_exit" in kind:
            return _SPECIAL_FILES["bed_exit"]
        if "code_blue" in kind:
            return _SPECIAL_FILES["code_blue"]
        # IV pump / cabinet alarms — fall through (device's own tone).
        return None

    return None


def annotate(alarms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `audio_url` + `audio_priority` to every alarm in-place
    and return the list.  Safe on alarms that have no curated audio
    (audio_url stays None)."""
    for a in alarms:
        a["audio_url"] = audio_url_for(a)
        a["audio_priority"] = severity_to_priority(
            (a.get("severity") or ""))
    return alarms
