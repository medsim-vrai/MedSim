"""FR-018 S2 — a character turn weaves in the patient's LIVE support documents
(context docs + revealed on_ask), and a student "bringing up" an on_ask doc
auto-reveals it so it joins the turn. The Anthropic call is stubbed; we assert what
reaches the model's system prompt."""
from __future__ import annotations

import pytest

from portal import runtime
from portal import scanned_docs as sd


@pytest.fixture(autouse=True)
def _isolated_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "DOCS_DIR", tmp_path / "scanned")


@pytest.fixture
def cap(monkeypatch):
    """Stub anthropic.Anthropic so take_turn runs offline; capture the kwargs
    (incl. the assembled `system` prompt) it would send to the model."""
    seen: dict = {}

    class _Resp:
        content = [type("B", (), {"type": "text", "text": "ok"})()]

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            return _Resp()

    class _Client:
        def __init__(self, **kw):
            self.messages = _Msgs()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    return seen


def _session(enc_id="ENC1"):
    return runtime.create_session_from_data(
        scenario={"id": enc_id, "name": "Case", "patient": {}},
        characters={"P-1": {"id": "P-1", "name": "Pat", "role": "patient"}},
        api_key="sk-test",
    )


def test_context_doc_reaches_the_system_prompt(cap):
    sd.save_doc("ENC1", "P-1", "cbc.png", b"x", source="instructor",
                ai_mode="context", doc_type="Lab report", purpose="WBC 14.2 (high)")
    sess = _session()
    r = runtime.take_turn(sess.id, "P-1", "how are you feeling?")
    assert r["ok"], r
    assert "DOCUMENTS ON FILE" in cap["system"] and "WBC 14.2" in cap["system"]


def test_dormant_on_ask_hidden_until_brought_up(cap):
    sd.save_doc("ENC1", "P-1", "old_ekg.png", b"x", source="instructor",
                ai_mode="on_ask", doc_type="ECG / Diagnostics", purpose="prior EKG")
    sess = _session()
    runtime.take_turn(sess.id, "P-1", "what's for lunch?")     # unrelated
    assert "prior EKG" not in cap["system"]
    runtime.take_turn(sess.id, "P-1", "can I see your old EKG?")  # brings it up
    assert "prior EKG" in cap["system"]


def test_no_docs_no_block(cap):
    sess = _session("EMPTY")
    runtime.take_turn(sess.id, "P-1", "hello")
    assert "DOCUMENTS ON FILE" not in cap["system"]
