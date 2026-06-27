"""FR-014 step 2 — doc_summary pure helpers. The networked summarize() isn't
exercised here (no API key in CI); we pin build_content / supported / the no-key
guard, which is where the real branching logic lives."""
from __future__ import annotations

import base64

import pytest

from portal import doc_summary


def test_supported_types():
    for ext in ("png", "jpg", "jpeg", "webp", "gif", "pdf", "PNG", "PDF"):
        assert doc_summary.supported(ext), ext
    for ext in ("heic", "heif", "txt", "docx", "", None):
        assert not doc_summary.supported(ext), ext


def test_build_content_image_block_and_base64():
    raw = b"\x89PNG\r\n\x1a\n fake bytes"
    content = doc_summary.build_content(raw, "png")
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[0]["source"]["data"] == base64.standard_b64encode(raw).decode("ascii")
    assert content[1]["type"] == "text" and "chart" in content[1]["text"].lower()


def test_build_content_jpg_maps_to_jpeg():
    content = doc_summary.build_content(b"x", "jpg")
    assert content[0]["source"]["media_type"] == "image/jpeg"


def test_build_content_pdf_is_document_block():
    content = doc_summary.build_content(b"%PDF-1.4", "pdf")
    assert content[0]["type"] == "document"
    assert content[0]["source"]["media_type"] == "application/pdf"


def test_build_content_includes_patient_label_when_given():
    content = doc_summary.build_content(b"x", "png", patient_label="Jane Doe")
    assert "Jane Doe" in content[1]["text"]
    # ...and omits the parenthetical when not given
    assert "(" not in doc_summary.build_content(b"x", "png")[1]["text"]


def test_build_content_rejects_unsupported():
    with pytest.raises(ValueError):
        doc_summary.build_content(b"x", "heic")


def test_summarize_requires_key():
    with pytest.raises(ValueError):
        doc_summary.summarize(b"x", "png", api_key="")
