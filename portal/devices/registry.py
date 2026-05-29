"""Device registry — maps (device_kind, device_model) → bundle path.

Each model directory is expected to contain at least:

    skin.svg     The Phase-2 overlay (cairosvg-safe, ID-bound).
    spec.json    Screens, controls, alarm map, optional catalogs.
    engine.py    OPTIONAL — only if this model needs to override the
                 default engine for its kind. The reference devices in
                 v6.0 (Alaris, Kangaroo OMNI, Pyxis) supply this; the
                 12 future re-skin models will not need to.

The registry deliberately does NOT pre-load specs at import — they're
read on demand by ``bootstrap()`` so the operator can edit ``spec.json``
without a server restart during development.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEVICES_ROOT = Path(__file__).parent

# device_kind → relative-from-_DEVICES_ROOT subdirectory holding models
KIND_DIRS: dict[str, str] = {
    "pump_iv":      "pumps",
    "pump_enteral": "pumps",
    "cabinet":      "cabinets",
    # M51 — Patient Integrated Alarm: a tablet at the bedside that
    # combines call bell + bed alarm + code blue + intercom on one
    # screen. Unlike pumps/cabinets which render a vendor skin SVG,
    # the PIA renders a dedicated `pia_app.html` template — the
    # spec/skin in `pia/pia_v1/` is a minimal stub kept only so the
    # registry's load_spec/load_skin don't fail for legacy callers.
    "patient_integrated_alarm": "pia",
}

# v6.0 ships these three reference models. Re-skins live in the same
# tree but aren't listed here — they're discovered by scanning at boot.
REFERENCE_MODELS: dict[str, list[str]] = {
    "pump_iv":      ["alaris"],
    "pump_enteral": ["kangaroo_omni"],
    "cabinet":      ["pyxis"],
    "patient_integrated_alarm": ["pia_v1"],
}


def list_kinds() -> list[str]:
    """Phase 7 1.5 — public-facing list of device kinds. Used by the
    M22 Per-Patient Console + M27 Nursing Station to enumerate what
    devices exist on an encounter. Returns kinds in insertion order
    (pumps before cabinets) so the UI ordering is stable. M29
    future-device stubs (call bell, bed alarm, code blue button,
    fire alarm) will register themselves in this dict at import time."""
    return list(KIND_DIRS.keys())


def model_root(device_kind: str, device_model: str) -> Path:
    sub = KIND_DIRS.get(device_kind)
    if sub is None:
        raise KeyError(f"unknown device_kind: {device_kind!r}")
    return _DEVICES_ROOT / sub / device_model


def available_models(device_kind: str) -> list[str]:
    """Every model dir under this kind whose spec.json declares the
    matching ``device_kind``.

    V6 bug fix: ``pumps/`` carries BOTH IV (alaris) and enteral
    (kangaroo_omni) folders. The prior version returned every model
    that had a spec.json + skin.svg, so the operator's "Add device"
    dropdown for IV pumps listed kangaroo_omni (and vice versa). When
    the operator picked the wrong pair, the engine for one device_kind
    loaded the spec for another, leading to KeyError 'channels' (IV
    engine asking the enteral spec for its channel list). Now each
    model is only listed under its own declared kind.
    """
    sub = KIND_DIRS.get(device_kind)
    if sub is None:
        return []
    root = _DEVICES_ROOT / sub
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not ((entry / "skin.svg").is_file() and (entry / "spec.json").is_file()):
            continue
        try:
            spec = json.loads((entry / "spec.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Only include models whose spec self-identifies as the right kind.
        if spec.get("device_kind") != device_kind:
            continue
        found.append(entry.name)
    return found


def load_spec(device_kind: str, device_model: str) -> dict[str, Any]:
    spec_path = model_root(device_kind, device_model) / "spec.json"
    return json.loads(spec_path.read_text(encoding="utf-8"))


def load_skin(device_kind: str, device_model: str) -> str:
    skin_path = model_root(device_kind, device_model) / "skin.svg"
    return skin_path.read_text(encoding="utf-8")
