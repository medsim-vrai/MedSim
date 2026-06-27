"""FR-014 step 2 — AI summary of a scanned chart document.

A student scans a report/lab/form (FR-014 step 1); this drafts a short, factual
clinical summary the student then EDITS and APPROVES into the chart (the draft is
never auto-committed — FR-008 "nothing live until confirmed" posture). Claude
reads the image (vision) or PDF (document block) directly.

The module is split like scenario_gen.py: prompt/content assembly (`build_content`,
`supported`) is pure + unit-testable; only `summarize()` makes the Anthropic call.
"""
from __future__ import annotations

import base64
import os
from typing import Any

# Vision/PDF is quality-sensitive but one-shot — use a capable current model with
# an env override per deployment / cost posture (mirrors scenario_gen.GEN_MODEL).
SUMMARY_MODEL = os.environ.get("MEDSIM_DOC_SUMMARY_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 700

# Media types Claude vision accepts. HEIC/HEIF are NOT supported by the vision API,
# so a phone-native .heic must be re-scanned as JPG/PNG (the caller surfaces this).
_VISION = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
           "webp": "image/webp", "gif": "image/gif"}
_PDF_EXT = {"pdf"}

SYSTEM = (
    "You are a clinical scribe helping a healthcare trainee summarize a scanned "
    "document (a lab result, diagnostic report, or form) so it can go into a "
    "patient chart. Read the document and write a SHORT, factual summary a "
    "clinician could drop into the record:\n"
    "  - the document type and date (if visible),\n"
    "  - the key findings / values WITH units,\n"
    "  - any abnormal / flagged results, called out plainly.\n"
    "Use plain clinical language and short bullet points. Do NOT invent values you "
    "cannot read; if the document is unreadable or not a clinical document, say so "
    "in one line. This is synthetic training data. Output ONLY the summary — no "
    "preamble, no closing remarks."
)


def supported(ext: str) -> bool:
    """True if we can ask Claude to read this document type."""
    e = (ext or "").lower()
    return e in _VISION or e in _PDF_EXT


def build_content(data: bytes, ext: str, patient_label: str = "") -> list[dict[str, Any]]:
    """Build the Anthropic message `content` list (the document block + the ask).
    Pure — no network. Raises ValueError on an unsupported type."""
    e = (ext or "").lower()
    b64 = base64.standard_b64encode(data or b"").decode("ascii")
    if e in _VISION:
        block: dict[str, Any] = {"type": "image", "source": {
            "type": "base64", "media_type": _VISION[e], "data": b64}}
    elif e in _PDF_EXT:
        block = {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf", "data": b64}}
    else:
        raise ValueError(f"can't summarize a .{e or '?'} document (images or PDF only)")
    ask = "Summarize this scanned document for the patient chart."
    if (patient_label or "").strip():
        ask += f" (Chart: {patient_label.strip()}.)"
    return [block, {"type": "text", "text": ask}]


def summarize(data: bytes, ext: str, *, api_key: str, patient_label: str = "") -> str:
    """Draft a chart summary of the scanned document. Returns the summary text.
    Raises ValueError (no key / unsupported type) or RuntimeError (API failure)."""
    if not (api_key or "").strip():
        raise ValueError("no Anthropic API key")
    content = build_content(data, ext, patient_label)   # validates type before any network
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=SUMMARY_MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(getattr(b, "text", "") for b in (resp.content or []))
    except Exception as exc:  # noqa: BLE001 — surface a clean message to the API layer
        raise RuntimeError(str(exc)) from exc
    return text.strip()
