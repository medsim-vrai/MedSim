"""FR-014 step 1 — scanned-document store + the records-terminal attach/list/serve
API (a student scans a report/lab into the patient chart)."""
from __future__ import annotations

import pytest

from portal import scanned_docs as sd


@pytest.fixture(autouse=True)
def _isolated_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "DOCS_DIR", tmp_path / "scanned")


# ── store ────────────────────────────────────────────────────────────────────

def test_save_list_get_path_roundtrip():
    rec = sd.save_doc("enc1", "P-1", "lab report.png", b"imgbytes",
                      author_name="Sam Nurse", author_initials="sn")
    assert rec["ext"] == "png"
    assert rec["filename"] == "lab report.png"
    assert rec["author_initials"] == "SN"           # upper-cased
    assert rec["summary_approved"] is False
    assert [d["id"] for d in sd.list_docs("enc1")] == [rec["id"]]
    assert sd.list_docs("enc1", "P-2") == []         # persona filter
    assert sd.get_doc("enc1", rec["id"])["filename"] == "lab report.png"
    p = sd.doc_path("enc1", rec["id"])
    assert p is not None and p.read_bytes() == b"imgbytes"


def test_save_rejects_unsupported_type():
    with pytest.raises(ValueError):
        sd.save_doc("enc1", "P-1", "archive.zip", b"PK")


def test_filename_basename_only():
    rec = sd.save_doc("enc1", "P-1", "/etc/evil/passwd.png", b"x")
    assert rec["filename"] == "passwd.png"           # path stripped


def test_set_summary():
    rec = sd.save_doc("enc1", "P-1", "report.pdf", b"%PDF-1.4")
    upd = sd.set_summary("enc1", rec["id"], "  short report  ", approved=True)
    assert upd["summary"] == "short report" and upd["summary_approved"] is True
    assert sd.set_summary("enc1", "nope", "x") is None


# ── FR-018 — instructor support docs: roles + reveal ──────────────────────────

def test_instructor_doc_fields_and_reveal():
    rec = sd.save_doc("enc1", "P-1", "old_ekg.png", b"x", source="instructor",
                      purpose="prior EKG for comparison", ai_mode="on_ask")
    assert rec["source"] == "instructor"
    assert rec["purpose"] == "prior EKG for comparison"
    assert rec["ai_mode"] == "on_ask" and rec["revealed"] is False
    upd = sd.set_reveal("enc1", rec["id"])
    assert upd["revealed"] is True and "reveal_ts" in upd
    assert sd.set_reveal("enc1", "nope") is None


def test_ai_mode_normalizes():
    assert sd.save_doc("e", "P", "a.pdf", b"%PDF", ai_mode="Context")["ai_mode"] == "context"
    assert sd.save_doc("e", "P", "b.pdf", b"%PDF", ai_mode="BOGUS")["ai_mode"] == ""
    assert sd.save_doc("e", "P", "c.pdf", b"%PDF")["ai_mode"] == ""    # student-doc default


def test_instructor_doc_type_and_section():
    rec = sd.save_doc("e", "P", "ekg.png", b"x", source="instructor",
                      doc_type="ECG / Diagnostics", section="Diagnostics")
    assert rec["doc_type"] == "ECG / Diagnostics" and rec["section"] == "Diagnostics"


# ── FR-018 S2 — AI-context selection + auto-reveal on mention ──────────────────

def test_is_ai_live():
    assert sd.is_ai_live({"ai_mode": "context"})
    assert not sd.is_ai_live({"ai_mode": "on_ask"})
    assert sd.is_ai_live({"ai_mode": "on_ask", "revealed": True})
    assert not sd.is_ai_live({"ai_mode": ""})


def test_prompt_block_filters_to_ai_live():
    sd.save_doc("e", "P", "cbc.png", b"x", source="instructor",
                ai_mode="context", doc_type="Lab report", purpose="CBC trend")
    ask = sd.save_doc("e", "P", "ekg.png", b"x", source="instructor",
                      ai_mode="on_ask", doc_type="ECG", purpose="prior tracing")
    blk = sd.prompt_block_for("e", "P")
    assert "Lab report" in blk and "CBC trend" in blk      # context doc in
    assert "ECG" not in blk                                 # dormant on_ask out
    sd.set_reveal("e", ask["id"], True)
    assert "ECG" in sd.prompt_block_for("e", "P")           # revealed on_ask now in


def test_prompt_block_empty_when_no_live_docs():
    sd.save_doc("e", "P", "x.png", b"x", source="instructor", ai_mode="on_ask", doc_type="ECG")
    assert sd.prompt_block_for("e", "P") == ""              # only a dormant on_ask


def test_reveal_on_mention_keyword_match():
    sd.save_doc("e", "P", "old_ekg.png", b"x", source="instructor",
                ai_mode="on_ask", doc_type="ECG / Diagnostics",
                purpose="prior EKG for comparison")
    assert sd.reveal_on_mention("e", "P", "what's the plan today?") == []   # no mention
    rev = sd.reveal_on_mention("e", "P", "can I see the old EKG?")          # mentions EKG
    assert len(rev) == 1 and rev[0]["revealed"] is True
    assert sd.reveal_on_mention("e", "P", "the ekg again") == []            # idempotent


# ── attach / list / serve API ────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("MEDSIM_RESUME", "0")
    from portal import auth, control_room, credentials, server as server_mod
    sb = fake_home / ".medsim"
    sb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sb)
    monkeypatch.setattr(credentials, "VAULT_PATH", sb / "vault.enc")
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize("test_passwd_xyz_8chars")
    vault = credentials.unlock("test_passwd_xyz_8chars")
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")   # room start requires a key
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "FR014",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                        "patient_persona_id": "P-014", "personas": ["P-014"],
                        "ehr_id": "helix"}],
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_api_attach_list_serve(client):
    _start_room(client)
    png = b"\x89PNG\r\n\x1a\n fake-image-bytes"
    r = client.post("/api/medical_records/P-014/documents",
                    files={"file": ("lab.png", png, "image/png")},
                    data={"author_name": "Sam Nurse", "author_initials": "SN"})
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert doc["ext"] == "png" and doc["author_initials"] == "SN"

    lst = client.get("/api/medical_records/P-014/documents").json()["documents"]
    assert len(lst) == 1 and lst[0]["id"] == doc["id"]

    fr = client.get(f"/api/medical_records/P-014/documents/{doc['id']}/file")
    assert fr.status_code == 200
    assert fr.content.startswith(b"\x89PNG")


def test_api_attach_unsupported_type_400(client):
    _start_room(client)
    r = client.post("/api/medical_records/P-014/documents",
                    files={"file": ("notes.zip", b"PK\x03\x04", "application/zip")})
    assert r.status_code == 400


def test_api_attach_unknown_persona_404(client):
    _start_room(client)
    r = client.post("/api/medical_records/NOPE/documents",
                    files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert r.status_code == 404


# ── FR-014 step 2 — AI summary save / approve (no network) ────────────────────

def test_api_save_summary_roundtrip(client):
    _start_room(client)
    doc = client.post("/api/medical_records/P-014/documents",
                      files={"file": ("lab.png", b"\x89PNG\r\n", "image/png")}).json()["document"]
    # Student saves + approves an edited summary — no AI/network involved.
    r = client.post(f"/api/medical_records/P-014/documents/{doc['id']}/summary",
                    json={"summary": "  WBC 14.2 (high); rest WNL  ", "approved": True})
    assert r.status_code == 200, r.text
    out = r.json()["document"]
    assert out["summary"] == "WBC 14.2 (high); rest WNL"
    assert out["summary_approved"] is True
    lst = client.get("/api/medical_records/P-014/documents").json()["documents"]
    assert lst[0]["summary_approved"] is True            # persisted


def test_api_summarize_unsupported_type_is_friendly(client):
    _start_room(client)
    # HEIC uploads are allowed (phone-native) but Claude vision can't read them →
    # the summarize route must DECLINE cleanly (no network) rather than error.
    doc = client.post("/api/medical_records/P-014/documents",
                      files={"file": ("photo.heic", b"ftyp-heic-fake", "image/heic")}).json()["document"]
    r = client.post(f"/api/medical_records/P-014/documents/{doc['id']}/summarize")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and "isn't available" in body["error"]


def test_api_save_summary_unknown_doc_404(client):
    _start_room(client)
    r = client.post("/api/medical_records/P-014/documents/nope/summary",
                    json={"summary": "x"})
    assert r.status_code == 404


def test_api_instructor_import_with_role_and_section(client):
    _start_room(client)
    r = client.post("/api/medical_records/P-014/documents",
                    files={"file": ("prior_ekg.png", b"\x89PNG\r\n", "image/png")},
                    data={"source": "instructor", "doc_type": "ECG / Diagnostics",
                          "section": "Diagnostics", "purpose": "prior EKG for comparison",
                          "ai_mode": "on_ask"})
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert doc["source"] == "instructor"
    assert doc["doc_type"] == "ECG / Diagnostics" and doc["section"] == "Diagnostics"
    assert doc["ai_mode"] == "on_ask" and doc["purpose"] == "prior EKG for comparison"


def test_api_student_upload_is_always_ai_context(client):
    # FR-018 — a student-added doc is ALWAYS AI context (no role choice on the
    # student side); the route forces it even if the form omits ai_mode.
    _start_room(client)
    doc = client.post("/api/medical_records/P-014/documents",
                      files={"file": ("scan.png", b"\x89PNG", "image/png")}).json()["document"]
    assert doc["source"] == "scan" and doc["ai_mode"] == "context"
