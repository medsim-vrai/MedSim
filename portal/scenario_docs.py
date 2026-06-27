"""FR-018 S4 — support documents authored INTO a scenario (persistent, reusable).

Unlike scanned_docs (per-RUN, under data/scanned_documents/, cleared by reset),
these live under data/scenario_docs/<scenario_id>/ and PERSIST with the scenario.
The instructor copies a scenario's docs into a running bed via copy_to_encounter(),
which writes them into that run's scanned_docs store — so each run gets its own
reveal state and the docs behave exactly like a live injection (FR-018 S2/S3).

Records carry the authored role (doc_type / section / purpose / ai_mode) and an
auto-generated summary (so the AI content travels with the scenario). Reveal state
is NOT stored here — it's per-run, set on the copy.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from . import scanned_docs as _sd

DOCS_DIR = Path(__file__).resolve().parent / "data" / "scenario_docs"
ALLOWED_EXT = _sd.ALLOWED_EXT
AI_MODES = _sd.AI_MODES


def _safe(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(token or ""))[:64]


def _dir(scenario_id: str) -> Path:
    return DOCS_DIR / _safe(scenario_id)


def _index_path(scenario_id: str) -> Path:
    return _dir(scenario_id) / "index.json"


def _load(scenario_id: str) -> list[dict[str, Any]]:
    try:
        p = _index_path(scenario_id)
        if p.exists():
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def _save(scenario_id: str, items: list[dict[str, Any]]) -> None:
    d = _dir(scenario_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "index.json.tmp"
    tmp.write_text(json.dumps(items, indent=2), "utf-8")
    tmp.replace(_index_path(scenario_id))


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "").lower()


def save_doc(scenario_id: str, filename: str, data: bytes, *, doc_type: str = "",
             section: str = "", purpose: str = "", ai_mode: str = "",
             summary: str = "", content_type: str = "") -> dict[str, Any]:
    """Persist a support document on a scenario. Raises ValueError on an
    unsupported type. Returns the new record."""
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXT:
        raise ValueError(f"unsupported document type: .{ext or '?'} (images or PDF only)")
    doc_id = secrets.token_urlsafe(8)
    d = _dir(scenario_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc_id}.{ext}").write_bytes(data)
    rec = {
        "id": doc_id,
        "ext": ext,
        "filename": Path(filename or f"document.{ext}").name[:120],
        "content_type": content_type or _sd._CONTENT_TYPE.get(ext, "application/octet-stream"),
        "size": len(data),
        "ts": time.time(),
        "doc_type": (doc_type or "").strip()[:40],
        "section": (section or "").strip()[:40],
        "purpose": (purpose or "").strip()[:300],
        "ai_mode": (lambda m: m if m in AI_MODES else "")((ai_mode or "").strip().lower()),
        "summary": (summary or "").strip(),
    }
    items = _load(scenario_id)
    items.append(rec)
    _save(scenario_id, items)
    return rec


def list_docs(scenario_id: str) -> list[dict[str, Any]]:
    return _load(scenario_id)


def get_doc(scenario_id: str, doc_id: str) -> dict[str, Any] | None:
    return next((it for it in _load(scenario_id) if it.get("id") == doc_id), None)


def doc_path(scenario_id: str, doc_id: str) -> Path | None:
    rec = get_doc(scenario_id, doc_id)
    if rec is None:
        return None
    p = _dir(scenario_id) / f"{_safe(doc_id)}.{rec.get('ext', '')}"
    return p if p.exists() else None


def set_summary(scenario_id: str, doc_id: str, summary: str) -> dict[str, Any] | None:
    items = _load(scenario_id)
    for it in items:
        if it.get("id") == doc_id:
            it["summary"] = (summary or "").strip()
            _save(scenario_id, items)
            return it
    return None


def delete_doc(scenario_id: str, doc_id: str) -> bool:
    items = _load(scenario_id)
    keep = [it for it in items if it.get("id") != doc_id]
    if len(keep) == len(items):
        return False
    p = doc_path(scenario_id, doc_id)
    if p is not None:
        try:
            p.unlink()
        except OSError:
            pass
    _save(scenario_id, keep)
    return True


def copy_to_encounter(scenario_id: str, enc_id: str, persona_id: str) -> int:
    """Copy this scenario's authored docs into a running encounter's scanned_docs
    store (source=instructor, with the authored role + summary; fresh per-run reveal
    state). Returns the count copied."""
    n = 0
    for rec in _load(scenario_id):
        p = doc_path(scenario_id, rec.get("id"))
        if p is None:
            continue
        try:
            data = p.read_bytes()
            new = _sd.save_doc(
                enc_id, persona_id, rec.get("filename") or f"doc.{rec.get('ext')}", data,
                source="instructor", content_type=rec.get("content_type", ""),
                doc_type=rec.get("doc_type", ""), section=rec.get("section", ""),
                purpose=rec.get("purpose", ""), ai_mode=rec.get("ai_mode", ""))
            if rec.get("summary"):
                _sd.set_summary(enc_id, new["id"], rec["summary"], approved=True)
            n += 1
        except Exception:  # noqa: BLE001 — skip a bad doc, copy the rest
            continue
    return n
