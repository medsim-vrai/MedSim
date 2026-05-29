"""V7 Phase 7 — ECG waveform library (M24).

Static catalog of common cardiac rhythms. Each entry exposes
parameters (rate range, complex shape) that the client renderer
(``portal/static/ecg_strip.js``) turns into a continuous scrolling
SVG strip.

No physiological model — the catalog is a fixed library of common
clinical waveforms scenario authors can pick from. Until a true
physiology engine lands (a v7.2 candidate), the rhythm on each
encounter is whatever the instructor selects via the M25
Per-Patient Console's ECG picker.

The 11 rhythms cover the common NCLEX-relevant cardiac scenarios:

  - **nsr**          — Normal Sinus Rhythm; the baseline rhythm
  - **sinus_tachy**  — Sinus Tachycardia (HR > 100, normal shape)
  - **sinus_brady**  — Sinus Bradycardia (HR < 60)
  - **afib**         — Atrial Fibrillation (irregularly irregular)
  - **aflutter**     — Atrial Flutter (sawtooth baseline, regular)
  - **vtach_mono**   — Monomorphic Ventricular Tachycardia
  - **vtach_poly**   — Polymorphic VT / Torsades de Pointes
  - **vfib**         — Ventricular Fibrillation (chaotic)
  - **asystole**     — Flatline (no electrical activity)
  - **pea**          — Pulseless Electrical Activity (organized QRS, no pulse)
  - **paced**        — Paced rhythm (pacer spikes + wide QRS)

Each waveform's `complex` is a list of (relative_time, amplitude)
pairs describing one heartbeat cycle. The renderer interpolates
between them and tiles the cycle across the strip at the rhythm's
configured rate. `noise` is the baseline-jitter amplitude (in mV).
"""
from __future__ import annotations

from typing import Any


# ── Waveform definitions ─────────────────────────────────────────────
#
# Each beat-cycle is described as a sparse list of (t, amplitude)
# control points. The renderer linearly interpolates between them and
# wraps the cycle at the rhythm's beat interval. t is fraction of one
# beat cycle (0.0 → 1.0); amplitude is mV (typical strip ±1.5 mV).

_NSR_BEAT = [
    (0.00,  0.0),
    (0.08,  0.15),  # P
    (0.12,  0.0),
    (0.18, -0.10),  # Q
    (0.20,  1.20),  # R
    (0.22, -0.30),  # S
    (0.30,  0.0),
    (0.45,  0.30),  # T
    (0.55,  0.0),
    (1.00,  0.0),
]
_TACHY_BEAT = _NSR_BEAT   # same shape, faster rate
_BRADY_BEAT = _NSR_BEAT   # same shape, slower rate

# Atrial fibrillation — fibrillatory baseline (no P), irregularly
# irregular spacing. The client renderer adds the irregularity by
# perturbing the next-beat interval ±25%.
_AFIB_BEAT = [
    (0.00,  0.0),
    (0.05,  0.05), (0.10, -0.04), (0.15,  0.06),  # fib baseline
    (0.20,  1.10),                                 # R
    (0.22, -0.30),                                 # S
    (0.30,  0.0),
    (0.45,  0.25),                                 # T (sometimes absent)
    (0.55,  0.0),
    (1.00,  0.0),
]

# Atrial flutter — sawtooth baseline, regular ventricular response.
# Default 2:1 block → ventricular rate ~ 150 (atrial 300).
_AFLUTTER_BEAT = [
    (0.00,  0.0),
    (0.05,  0.18), (0.10, -0.08),
    (0.15,  0.18), (0.20, -0.08),  # sawtooth Fwaves
    (0.25,  0.18), (0.30, -0.08),
    (0.40,  1.10),                  # R
    (0.42, -0.30),                  # S
    (0.50,  0.0),
    (0.65,  0.20),                  # T
    (1.00,  0.0),
]

# Monomorphic VT — wide-complex, regular, no P.
_VTACH_MONO_BEAT = [
    (0.00,  0.0),
    (0.05,  0.6), (0.15,  1.1), (0.30,  0.4),   # wide R
    (0.45, -0.8), (0.55, -0.3),                 # wide negative tail
    (0.75,  0.0),
    (1.00,  0.0),
]

# Polymorphic VT / Torsades — twisting around the baseline.
_VTACH_POLY_BEAT = [
    (0.00,  0.0),
    (0.10,  1.0), (0.25, -0.9), (0.40,  0.8),
    (0.55, -1.0), (0.70,  0.5), (0.85, -0.4),
    (1.00,  0.0),
]

# Ventricular fibrillation — chaotic high-frequency, no clear beats.
# The renderer treats this as noise-only with no cycle structure.
_VFIB_BEAT = [
    (0.00,  0.0),
    (0.10,  0.7), (0.20, -0.6), (0.30,  0.5),
    (0.40, -0.7), (0.55,  0.4), (0.65, -0.5),
    (0.80,  0.6), (0.95, -0.3),
    (1.00,  0.0),
]

# Asystole — flatline.
_ASYSTOLE_BEAT = [(0.00, 0.0), (1.00, 0.0)]

# PEA — organized QRS rhythm but no pulse. Looks like a slow,
# wide-complex rhythm visually; clinical correlation distinguishes
# from VT (no pulse).
_PEA_BEAT = [
    (0.00,  0.0),
    (0.20,  0.6), (0.30,  0.9), (0.40,  0.4),
    (0.55, -0.5),
    (0.75,  0.10),
    (1.00,  0.0),
]

# Paced rhythm — sharp pacer spike followed by wide ventricular
# complex.
_PACED_BEAT = [
    (0.00,  0.0),
    (0.10,  1.5),                                  # pacer spike
    (0.12, -0.2),
    (0.20,  0.8), (0.30,  1.1), (0.40,  0.4),     # wide QRS
    (0.55, -0.5),
    (0.70,  0.20),
    (1.00,  0.0),
]


CATALOG: list[dict[str, Any]] = [
    {"id": "nsr",          "label": "Normal sinus rhythm (NSR)",
     "default_rate": 75,   "rate_range": (60, 100),  "regular": True,
     "noise": 0.02, "complex": _NSR_BEAT,
     "class": "normal", "common_use": "Baseline; stable patient."},
    {"id": "sinus_tachy",  "label": "Sinus tachycardia",
     "default_rate": 120,  "rate_range": (101, 160), "regular": True,
     "noise": 0.02, "complex": _TACHY_BEAT,
     "class": "tachy", "common_use": "Sepsis, dehydration, anxiety."},
    {"id": "sinus_brady",  "label": "Sinus bradycardia",
     "default_rate": 48,   "rate_range": (35, 59),   "regular": True,
     "noise": 0.02, "complex": _BRADY_BEAT,
     "class": "brady", "common_use": "Athlete; vagal; medication effect."},
    {"id": "afib",         "label": "Atrial fibrillation",
     "default_rate": 110,  "rate_range": (60, 160),  "regular": False,
     "noise": 0.08, "complex": _AFIB_BEAT, "irregularity": 0.25,
     "class": "irregular",
     "common_use": "AFib with controlled or rapid ventricular response."},
    {"id": "aflutter",     "label": "Atrial flutter (2:1)",
     "default_rate": 150,  "rate_range": (75, 150),  "regular": True,
     "noise": 0.03, "complex": _AFLUTTER_BEAT,
     "class": "regular",
     "common_use": "Atrial flutter with 2:1 / 4:1 conduction."},
    {"id": "vtach_mono",   "label": "Monomorphic VT",
     "default_rate": 180,  "rate_range": (150, 220), "regular": True,
     "noise": 0.04, "complex": _VTACH_MONO_BEAT,
     "class": "wide_tachy",
     "common_use": "Stable or unstable monomorphic VT."},
    {"id": "vtach_poly",   "label": "Polymorphic VT (torsades)",
     "default_rate": 200,  "rate_range": (180, 250), "regular": False,
     "noise": 0.05, "complex": _VTACH_POLY_BEAT, "irregularity": 0.15,
     "class": "wide_tachy",
     "common_use": "Torsades de pointes — long QT precursor."},
    {"id": "vfib",         "label": "Ventricular fibrillation",
     "default_rate": 0,    "rate_range": (0, 0),     "regular": False,
     "noise": 0.6,  "complex": _VFIB_BEAT,
     "class": "chaotic",
     "common_use": "Cardiac arrest — shockable rhythm."},
    {"id": "asystole",     "label": "Asystole",
     "default_rate": 0,    "rate_range": (0, 0),     "regular": True,
     "noise": 0.01, "complex": _ASYSTOLE_BEAT,
     "class": "flatline",
     "common_use": "Cardiac arrest — non-shockable."},
    {"id": "pea",          "label": "Pulseless electrical activity (PEA)",
     "default_rate": 50,   "rate_range": (20, 80),   "regular": True,
     "noise": 0.03, "complex": _PEA_BEAT,
     "class": "organized_no_pulse",
     "common_use": "Organized rhythm without a pulse — code blue."},
    {"id": "paced",        "label": "Paced rhythm",
     "default_rate": 70,   "rate_range": (60, 90),   "regular": True,
     "noise": 0.02, "complex": _PACED_BEAT,
     "class": "paced",
     "common_use": "After pacemaker placement; visible pacer spikes."},
]

# Quick id → entry lookup; the catalog list keeps insertion order
# for stable UI presentation.
_BY_ID: dict[str, dict[str, Any]] = {e["id"]: e for e in CATALOG}


def catalog() -> list[dict[str, Any]]:
    """Public read of the catalog. Each entry includes `id`, `label`,
    `default_rate`, `rate_range` (min, max), `regular`, `noise`,
    `complex` (sparse waveform points), `class`, `common_use`, and
    optional `irregularity` (for irregular rhythms)."""
    out = []
    for entry in CATALOG:
        e = dict(entry)
        # Cast tuple rate_range to list for JSON friendliness.
        if isinstance(e.get("rate_range"), tuple):
            e["rate_range"] = list(e["rate_range"])
        out.append(e)
    return out


def get(rhythm_id: str) -> dict[str, Any] | None:
    e = _BY_ID.get(rhythm_id)
    if e is None:
        return None
    out = dict(e)
    if isinstance(out.get("rate_range"), tuple):
        out["rate_range"] = list(out["rate_range"])
    return out


def is_valid_id(rhythm_id: str) -> bool:
    return rhythm_id in _BY_ID
