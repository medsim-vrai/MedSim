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
