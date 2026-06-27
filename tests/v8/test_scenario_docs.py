"""FR-018 S4 — scenario-authored support docs (persistent) + copy into a run's
scanned_docs store."""
from __future__ import annotations

import pytest

from portal import scanned_docs as sd
from portal import scenario_docs as scd


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(scd, "DOCS_DIR", tmp_path / "scenario_docs")
    monkeypatch.setattr(sd, "DOCS_DIR", tmp_path / "scanned")


def test_save_list_get_path_delete():
    rec = scd.save_doc("sepsis", "ekg.png", b"img", doc_type="ECG", section="Diagnostics",
                       purpose="prior", ai_mode="on_ask", summary="old MI")
    assert rec["ext"] == "png" and rec["ai_mode"] == "on_ask" and rec["summary"] == "old MI"
    assert [d["id"] for d in scd.list_docs("sepsis")] == [rec["id"]]
    assert scd.get_doc("sepsis", rec["id"])["doc_type"] == "ECG"
    p = scd.doc_path("sepsis", rec["id"])
    assert p is not None and p.read_bytes() == b"img"
    assert scd.delete_doc("sepsis", rec["id"]) is True
    assert scd.list_docs("sepsis") == []


def test_save_rejects_unsupported():
    with pytest.raises(ValueError):
        scd.save_doc("s", "notes.zip", b"PK")


def test_ai_mode_normalizes():
    assert scd.save_doc("s", "a.pdf", b"%PDF", ai_mode="Context")["ai_mode"] == "context"
    assert scd.save_doc("s", "b.pdf", b"%PDF", ai_mode="bogus")["ai_mode"] == ""


def test_copy_to_encounter():
    scd.save_doc("sepsis", "cbc.png", b"a", doc_type="Lab report", section="Labs",
                 ai_mode="context", summary="WBC 14")
    scd.save_doc("sepsis", "ekg.png", b"b", doc_type="ECG", ai_mode="on_ask", summary="old MI")
    n = scd.copy_to_encounter("sepsis", "ENC1", "P-1")
    assert n == 2
    docs = sd.list_docs("ENC1", "P-1")
    assert len(docs) == 2
    assert all(d["source"] == "instructor" for d in docs)
    assert {d["ai_mode"] for d in docs} == {"context", "on_ask"}
    assert {d["summary"] for d in docs} == {"WBC 14", "old MI"}     # summaries travel
    assert all(d["revealed"] is False for d in docs)                # reveal is per-run
