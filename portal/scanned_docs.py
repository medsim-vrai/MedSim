"""FR-014 — scanned documents attached to a patient's chart.

During a run, a student at the records terminal scans/uploads an image or PDF of a
report/lab; it's stored per-ENCOUNTER and shown in the chart's "Scanned documents"
section (mirrors real-world "scan into the EHR"). Step 2 (optional, AI) adds a
Claude-vision summary the student edits + approves — stored on the same record.

Storage mirrors the avatar-skin pattern: files under portal/data/scanned_documents/
<enc_id>/<doc_id>.<ext> with a per-encounter index.json sidecar. Gitignored; this
is per-run student content, cleared by reset.sh. Keyed by enc.id (ephemeral per
run) + tagged with persona_id so a multi-bed room lists the right patient's docs.

PHI posture: the records terminal already gates this behind sign-in + patient scope
+ a running room; uploads are synthetic training artifacts, never committed.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

# Read at call time so tests can monkeypatch.
DOCS_DIR = Path(__file__).resolve().parent / "data" / "scanned_documents"

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif", "heic", "heif", "pdf"}

# FR-018 — instructor support-document AI roles (any other value normalizes to "").
AI_MODES = {"context", "distraction", "on_ask"}
_CONTENT_TYPE = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "heic": "image/heic",
    "heif": "image/heic", "pdf": "application/pdf",
}


def _safe(token: str) -> str:
    """Defang an id used as a path segment (our ids are url-safe, but never trust)."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(token or ""))[:64]


def _enc_dir(enc_id: str) -> Path:
    return DOCS_DIR / _safe(enc_id)


def _index_path(enc_id: str) -> Path:
    return _enc_dir(enc_id) / "index.json"


def _load_index(enc_id: str) -> list[dict[str, Any]]:
    try:
        p = _index_path(enc_id)
        if p.exists():
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def _save_index(enc_id: str, items: list[dict[str, Any]]) -> None:
    d = _enc_dir(enc_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "index.json.tmp"
    tmp.write_text(json.dumps(items, indent=2), "utf-8")
    tmp.replace(_index_path(enc_id))   # atomic


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "").lower()


def save_doc(enc_id: str, persona_id: str, filename: str, data: bytes, *,
             author_name: str = "", author_initials: str = "",
             content_type: str = "", source: str = "scan", kind: str = "",
             purpose: str = "", ai_mode: str = "") -> dict[str, Any]:
    """Persist a document for (encounter, patient). `source` distinguishes a
    student "scan" (FR-014), an instructor-generated "report" (FR-015), and an
    instructor "instructor" support doc (FR-018). For FR-018: `purpose` is the
    instructor's note and `ai_mode` is the AI role (context | distraction | on_ask;
    any other value normalizes to ""). `kind` carries a report label. Raises
    ValueError on an unsupported type. Returns the new record."""
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXT:
        raise ValueError(f"unsupported document type: .{ext or '?'} "
                         f"(images or PDF only)")
    doc_id = secrets.token_urlsafe(8)
    d = _enc_dir(enc_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{doc_id}.{ext}").write_bytes(data)
    rec = {
        "id": doc_id,
        "persona_id": persona_id,
        "ext": ext,
        "filename": Path(filename or f"document.{ext}").name[:120],
        "content_type": content_type or _CONTENT_TYPE.get(ext, "application/octet-stream"),
        "size": len(data),
        "ts": time.time(),
        "author_name": (author_name or "").strip()[:80],
        "author_initials": (author_initials or "").upper().strip()[:4],
        "source": (source or "scan").strip()[:16],     # "scan" | "report" | "instructor"
        "kind": (kind or "").strip()[:40],              # report label, when source="report"
        "purpose": (purpose or "").strip()[:300],       # FR-018 — instructor note (instructor-only)
        "ai_mode": (lambda m: m if m in AI_MODES else "")((ai_mode or "").strip().lower()),
        "revealed": False,          # FR-018 on_ask — gates AI engagement, not student visibility
        "summary": "",              # FR-014 step 2 — AI draft, then student-approved
        "summary_approved": False,
    }
    items = _load_index(enc_id)
    items.append(rec)
    _save_index(enc_id, items)
    return rec


def list_docs(enc_id: str, persona_id: str | None = None) -> list[dict[str, Any]]:
    items = _load_index(enc_id)
    if persona_id is not None:
        items = [it for it in items if it.get("persona_id") == persona_id]
    return items


def get_doc(enc_id: str, doc_id: str) -> dict[str, Any] | None:
    return next((it for it in _load_index(enc_id) if it.get("id") == doc_id), None)


def doc_path(enc_id: str, doc_id: str) -> Path | None:
    rec = get_doc(enc_id, doc_id)
    if rec is None:
        return None
    p = _enc_dir(enc_id) / f"{_safe(doc_id)}.{rec.get('ext', '')}"
    return p if p.exists() else None


def set_summary(enc_id: str, doc_id: str, summary: str, *,
                approved: bool = False) -> dict[str, Any] | None:
    """FR-014 step 2 — store the (AI-drafted, student-edited) summary + approval."""
    items = _load_index(enc_id)
    for it in items:
        if it.get("id") == doc_id:
            it["summary"] = (summary or "").strip()
            it["summary_approved"] = bool(approved)
            it["summary_ts"] = time.time()
            _save_index(enc_id, items)
            return it
    return None


def set_reveal(enc_id: str, doc_id: str, revealed: bool = True) -> dict[str, Any] | None:
    """FR-018 — flip a reveal-on-ask instructor doc to live (revealed=True) so the
    AI starts engaging with it. Returns the updated record, or None if not found."""
    items = _load_index(enc_id)
    for it in items:
        if it.get("id") == doc_id:
            it["revealed"] = bool(revealed)
            it["reveal_ts"] = time.time()
            _save_index(enc_id, items)
            return it
    return None
