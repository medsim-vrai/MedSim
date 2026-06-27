"""FR-015 R1 — lab report generator: engine (build/override/flag/render/pdf/email)
+ instructor routes (preview/pdf/email/page)."""
from __future__ import annotations

import pytest

from portal import report_gen as rg

SEED = {
    "name": "Joe Diaz", "mrn": "M1", "dob": "1958-02-03", "sex": "male",
    "labs_recent": [
        {"panel": "BMP", "time": "T-6h", "values": [
            {"name": "K", "v": "4.2", "ref": "3.6-5.0", "flag": ""},
            {"name": "Na", "v": "138", "ref": "135-145", "flag": ""}]},
        {"panel": "CBC", "time": "T-6h", "values": [
            {"name": "WBC", "v": "8", "ref": "4-11", "flag": ""}]},
    ],
}


# ── engine ───────────────────────────────────────────────────────────────────

def test_flag_for():
    assert rg.flag_for("2.0", "3.6-5.0") == "L"
    assert rg.flag_for("6.0", "3.6-5.0") == "H"
    assert rg.flag_for("4.0", "3.6-5.0") == ""
    assert rg.flag_for("x", "3.6-5.0") == ""           # non-numeric
    assert rg.flag_for("4", "") == ""                  # unparseable ref


def test_available_panels():
    assert rg.available_panels(SEED) == ["BMP", "CBC"]


def test_panel_catalog_full_set():
    cat = rg.panel_catalog()
    names = [c["panel"] for c in cat]
    assert {"BMP", "CBC", "ABG", "Troponin", "BNP", "Coag"}.issubset(set(names))
    assert names[:2] == ["BMP", "CBC"]                 # common panels first
    bmp = next(c for c in cat if c["panel"] == "BMP")
    assert any(a["name"] == "K" and a["ref"] for a in bmp["analytes"])


def test_build_adds_panel_not_in_seed_from_catalog():
    cat = rg.panel_catalog()
    r = rg.build_lab_report(SEED, panels=["BMP", "Troponin"], catalog=cat)   # Troponin not seeded
    assert [p["panel"] for p in r["panels"]] == ["BMP", "Troponin"]
    trop = next(p for p in r["panels"] if p["panel"] == "Troponin")
    assert trop["values"] and all(v["ref"] for v in trop["values"])         # synthesized w/ ref ranges
    analyte = trop["values"][0]["name"]
    r2 = rg.build_lab_report(SEED, panels=["Troponin"], catalog=cat,
                             overrides=[{"panel": "Troponin", "analyte": analyte,
                                         "value": "12.5", "flag": "C"}])
    v0 = r2["panels"][0]["values"][0]
    assert v0["v"] == "12.5" and v0["flag"] == "C" and v0["overridden"] is True


def test_build_panel_filter_and_override():
    r = rg.build_lab_report(SEED, panels=["BMP"],
                            overrides=[{"panel": "BMP", "analyte": "K", "value": "6.5"}],
                            generated_by="Dr. X")
    assert [p["panel"] for p in r["panels"]] == ["BMP"]          # CBC filtered out
    k = next(v for v in r["panels"][0]["values"] if v["name"] == "K")
    assert k["v"] == "6.5" and k["flag"] == "H" and k["overridden"] is True
    na = next(v for v in r["panels"][0]["values"] if v["name"] == "Na")
    assert na["overridden"] is False                            # untouched
    assert r["patient"]["name"] == "Joe Diaz"
    assert r["meta"]["generated_by"] == "Dr. X"
    assert "TRAINING SIMULATION" in r["disclaimer"]


def test_override_explicit_flag_wins():
    r = rg.build_lab_report(SEED, overrides=[
        {"panel": "BMP", "analyte": "K", "value": "4.2", "flag": "C"}])
    k = next(v for v in r["panels"][0]["values"] if v["name"] == "K")
    assert k["flag"] == "C"


def test_report_html_and_student_strip():
    r = rg.build_lab_report(SEED, overrides=[{"panel": "BMP", "analyte": "K", "value": "6.5"}])
    h = rg.report_html(r)
    assert "Joe Diaz" in h and "WBC" in h and "Laboratory Report" in h
    assert 'class="ov"' in h                                    # instructor sees override dot
    assert 'class="ov"' not in rg.report_html(r, for_student=True)


def test_report_pdf_bytes():
    pdf = rg.report_pdf(rg.build_lab_report(SEED))
    assert pdf[:4] == b"%PDF" and len(pdf) > 500


def test_email_requires_config():
    r = rg.build_lab_report(SEED)
    with pytest.raises(ValueError):                             # no SMTP host
        rg.email_report(to="a@b.c", subject="x", body_text="y", pdf_bytes=b"",
                        filename="f.pdf", smtp={})
    with pytest.raises(ValueError):                             # no recipient
        rg.email_report(to="", subject="x", body_text="y", pdf_bytes=b"",
                        filename="f.pdf", smtp={"host": "localhost"})


# ── routes ───────────────────────────────────────────────────────────────────

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
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _start_room(client):
    r = client.post("/api/room/start", json={
        "label": "FR015",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                        "patient_persona_id": "P-014", "personas": ["P-014"],
                        "ehr_id": "helix"}]})
    assert r.status_code == 200, r.text


def test_api_preview_and_pdf(client):
    _start_room(client)
    r = client.post("/api/reports/lab/preview", json={"persona_id": "P-014", "mode": "live"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["report"]["panels"] and "<table" in j["html"]
    assert "BMP" in j["available_panels"]
    pr = client.post("/api/reports/lab/pdf", json={"persona_id": "P-014", "mode": "live"})
    assert pr.status_code == 200
    assert pr.headers["content-type"] == "application/pdf"
    assert pr.content[:4] == b"%PDF"


def test_api_preview_unknown_patient_404(client):
    assert client.post("/api/reports/lab/preview",
                       json={"persona_id": "NOPE"}).status_code == 404


def test_api_email_unconfigured_returns_error(client):
    _start_room(client)
    r = client.post("/api/reports/lab/email", json={"persona_id": "P-014", "to": "s@e.edu"})
    assert r.status_code == 200 and r.json()["ok"] is False     # no SMTP configured


def test_api_preview_requires_auth(client):
    from portal import auth
    client.cookies.delete(auth.COOKIE_NAME)
    assert client.post("/api/reports/lab/preview",
                       json={"persona_id": "P-014"}).status_code in (401, 403)


def test_reports_page_renders(client):
    r = client.get("/portal/reports")
    assert r.status_code == 200
    assert "Report Studio" in r.text or "Lab report" in r.text


def test_reports_page_lists_scenario_patients_prelaunch(client):
    # no room started → page lists scenario patients + the full panel catalog
    r = client.get("/portal/reports")
    assert r.status_code == 200
    assert 'value="P-' in r.text          # a scenario/library patient persona option
    assert "Troponin" in r.text           # full panel catalog checklist present


def test_reports_page_honors_selected_patients_param(client):
    # the wizard passes ?patients=<ids> for the SELECTED beds (pre-launch)
    r = client.get("/portal/reports?patients=P-014")
    assert r.status_code == 200
    assert 'value="P-014"' in r.text
    assert r.text.count('<option value="P-') == 1   # ONLY the selected patient


def test_reports_page_selection_wins_over_live_room(client):
    # a stale/previous live room must NOT override the instructor's explicit pick
    _start_room(client)                              # live room patient = P-014
    r = client.get("/portal/reports?patients=P-001")
    assert r.status_code == 200
    assert 'value="P-001"' in r.text                # the selected patient
    assert 'value="P-014"' not in r.text            # not the live bed


# ── FR-015 R3 — diagnostic reports: engine ───────────────────────────────────

def test_diagnostic_catalog_has_studies():
    cat = rg.diagnostic_catalog()
    ids = [s["id"] for s in cat]
    assert {"ecg", "cxr", "ct_head", "fast"}.issubset(set(ids))
    ecg = next(s for s in cat if s["id"] == "ecg")
    rhythm = next(f for f in ecg["fields"] if f["key"] == "rhythm")
    assert "Atrial fibrillation" in rhythm["options"]          # selectable rhythm
    assert any(f.get("multiline") for f in ecg["fields"])      # interpretation is multiline


def test_build_diagnostic_defaults_to_normal():
    r = rg.build_diagnostic_report(SEED, study_id="cxr")
    assert r["kind"] == "diagnostic" and r["study"] == "Chest X-ray"
    assert r["patient"]["name"] == "Joe Diaz"
    imp = next(f for f in r["fields"] if f["key"] == "impression")
    assert "No acute" in imp["value"]                          # normal-finding default
    assert "TRAINING SIMULATION" in r["disclaimer"]


def test_build_diagnostic_applies_fields_and_ignores_blank():
    r = rg.build_diagnostic_report(
        SEED, study_id="ecg",
        fields={"rhythm": "Atrial fibrillation", "rate": "", "interpretation": "AF with RVR."},
        generated_by="Dr. X", scenario_name="STEMI")
    fv = {f["key"]: f["value"] for f in r["fields"]}
    assert fv["rhythm"] == "Atrial fibrillation"               # instructor edit
    assert fv["rate"] == "78 bpm"                              # blank fell back to default
    assert fv["interpretation"] == "AF with RVR."
    assert r["meta"]["generated_by"] == "Dr. X"


def test_build_diagnostic_unknown_study_raises():
    with pytest.raises(ValueError):
        rg.build_diagnostic_report(SEED, study_id="mri_brain")


def test_diagnostic_html_and_pdf():
    r = rg.build_diagnostic_report(SEED, study_id="ecg",
                                   fields={"rhythm": "Ventricular tachycardia"})
    h = rg.diagnostic_html(r)
    assert "Joe Diaz" in h and "12-lead ECG" in h and "Ventricular tachycardia" in h
    assert "TRAINING SIMULATION" in h
    pdf = rg.diagnostic_pdf(r)
    assert pdf[:4] == b"%PDF" and len(pdf) > 500


# ── FR-015 R3 — diagnostic reports: routes ───────────────────────────────────

def test_api_diag_preview_and_pdf(client):
    _start_room(client)
    r = client.post("/api/reports/diagnostic/preview",
                    json={"persona_id": "P-014", "study_id": "ecg",
                          "fields": {"rhythm": "Atrial fibrillation"}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and "Atrial fibrillation" in j["html"]
    assert any(s["id"] == "ecg" for s in j["catalog"])
    pr = client.post("/api/reports/diagnostic/pdf",
                     json={"persona_id": "P-014", "study_id": "cxr"})
    assert pr.status_code == 200 and pr.headers["content-type"] == "application/pdf"
    assert pr.content[:4] == b"%PDF"


def test_api_diag_unknown_study_400(client):
    _start_room(client)
    r = client.post("/api/reports/diagnostic/preview",
                    json={"persona_id": "P-014", "study_id": "nope"})
    assert r.status_code == 400


def test_api_diag_email_unconfigured_returns_error(client):
    _start_room(client)
    r = client.post("/api/reports/diagnostic/email",
                    json={"persona_id": "P-014", "study_id": "ecg", "to": "s@e.edu"})
    assert r.status_code == 200 and r.json()["ok"] is False     # no SMTP configured


def test_reports_page_carries_diagnostic_catalog(client):
    r = client.get("/portal/reports")
    assert r.status_code == 200
    assert "12-lead ECG" in r.text and "🫀 Diagnostic" in r.text


# ── FR-015 R4 — referral / consult letters: engine ───────────────────────────

REFSEED = {**SEED, "chief_complaint": "chest pain",
           "problem_list": [{"name": "Essential hypertension"}, {"name": "Type 2 diabetes"}],
           "allergies": [{"substance": "Penicillin", "reaction": "rash"}]}


def test_referral_catalog_shape():
    cat = rg.referral_catalog()
    assert len(cat) == 1 and cat[0]["id"] == "consult"
    keys = [f["key"] for f in cat[0]["fields"]]
    assert keys[:2] == ["specialty", "urgency"]                # selects first
    spec = next(f for f in cat[0]["fields"] if f["key"] == "specialty")
    assert "Cardiology" in spec["options"]
    assert {"reason", "history", "findings", "question"}.issubset(set(keys))


def test_build_referral_defaults_from_seed():
    r = rg.build_referral_report(REFSEED)
    assert r["kind"] == "referral" and r["specialty"] == "Consult" and r["urgency"] == "Routine"
    fv = {f["key"]: f["value"] for f in r["fields"]}
    assert fv["reason"] == "chest pain"                        # from chief_complaint
    assert "Essential hypertension" in fv["history"] and "Penicillin" in fv["history"]
    assert "TRAINING SIMULATION" in r["disclaimer"]


def test_build_referral_applies_fields():
    r = rg.build_referral_report(
        REFSEED, fields={"specialty": "Cardiology", "urgency": "Urgent",
                         "reason": "Chest pain, rule out ACS", "question": "Cath?"},
        generated_by="Dr. X")
    assert r["specialty"] == "Cardiology" and r["urgency"] == "Urgent"
    fv = {f["key"]: f["value"] for f in r["fields"]}
    assert fv["reason"] == "Chest pain, rule out ACS" and fv["question"] == "Cath?"
    assert "Essential hypertension" in fv["history"]           # blank history → seed default
    assert r["meta"]["generated_by"] == "Dr. X"


def test_referral_html_and_pdf():
    r = rg.build_referral_report(REFSEED, fields={"specialty": "Cardiology", "reason": "ACS r/o"})
    h = rg.referral_html(r)
    assert "Cardiology Consult Service" in h and "ACS r/o" in h and "Joe Diaz" in h
    assert "TRAINING SIMULATION" in h
    pdf = rg.referral_pdf(r)
    assert pdf[:4] == b"%PDF" and len(pdf) > 500


# ── FR-015 R4 — referral / consult letters: routes ───────────────────────────

def test_api_referral_preview_and_pdf(client):
    _start_room(client)
    r = client.post("/api/reports/referral/preview",
                    json={"persona_id": "P-014",
                          "fields": {"specialty": "Cardiology", "reason": "chest pain"}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and "Cardiology" in j["html"] and "chest pain" in j["html"]
    assert j["catalog"][0]["id"] == "consult"
    pr = client.post("/api/reports/referral/pdf",
                     json={"persona_id": "P-014", "fields": {"specialty": "Neurology"}})
    assert pr.status_code == 200 and pr.headers["content-type"] == "application/pdf"
    assert pr.content[:4] == b"%PDF"


def test_api_referral_email_unconfigured_returns_error(client):
    _start_room(client)
    r = client.post("/api/reports/referral/email",
                    json={"persona_id": "P-014", "fields": {"specialty": "Cardiology"},
                          "to": "s@e.edu"})
    assert r.status_code == 200 and r.json()["ok"] is False     # no SMTP configured


def test_reports_page_carries_referral_catalog(client):
    r = client.get("/portal/reports")
    assert r.status_code == 200
    assert "✉ Referral" in r.text and "Consult / referral letter" in r.text


# ── FR-015 R5 — email hardening ──────────────────────────────────────────────

def test_parse_recipients_splits_validates_dedupes():
    assert rg.parse_recipients("a@b.co, c@d.org") == ["a@b.co", "c@d.org"]
    assert rg.parse_recipients("a@b.co; a@B.CO") == ["a@b.co"]      # case-insensitive dedupe
    assert rg.parse_recipients("  ") == []
    with pytest.raises(ValueError):
        rg.parse_recipients("not-an-email")
    with pytest.raises(ValueError):
        rg.parse_recipients("ok@x.io, bad")


def test_email_invalid_recipient_raises_before_send():
    # host IS configured, but the address is malformed → fail fast, no socket opened
    with pytest.raises(ValueError):
        rg.email_report(to="nope", subject="x", body_text="y", pdf_bytes=b"",
                        filename="f.pdf", smtp={"host": "localhost"})


# ── FR-015 R5 — attach report to chart ───────────────────────────────────────

def test_api_attach_lab_to_chart(client):
    _start_room(client)
    r = client.post("/api/reports/lab/attach", json={"persona_id": "P-014", "panels": ["BMP"]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["document"]["source"] == "report"
    assert j["document"]["kind"] == "Lab report" and j["document"]["ext"] == "pdf"
    # the attached report now shows up in the chart's Documents list
    docs = client.get("/api/medical_records/P-014/documents").json()["documents"]
    assert any(d["id"] == j["document"]["id"] and d["source"] == "report" for d in docs)


def test_api_attach_diagnostic_and_referral(client):
    _start_room(client)
    rd = client.post("/api/reports/diagnostic/attach",
                     json={"persona_id": "P-014", "study_id": "ecg",
                           "fields": {"rhythm": "Atrial fibrillation"}})
    assert rd.status_code == 200 and rd.json()["ok"]
    assert rd.json()["document"]["kind"] == "12-lead ECG"
    rr = client.post("/api/reports/referral/attach",
                     json={"persona_id": "P-014", "fields": {"specialty": "Cardiology"}})
    assert rr.status_code == 200 and rr.json()["ok"]
    assert "Cardiology" in rr.json()["document"]["kind"]


def test_api_attach_unknown_kind_404(client):
    _start_room(client)
    assert client.post("/api/reports/bogus/attach",
                       json={"persona_id": "P-014"}).status_code == 404


def test_api_attach_without_running_encounter_returns_error(client):
    # P-001 is not a bed in the started room → no chart to attach to → ok:false
    _start_room(client)                              # live room patient = P-014
    r = client.post("/api/reports/lab/attach", json={"persona_id": "P-001", "panels": ["BMP"]})
    assert r.status_code == 200 and r.json()["ok"] is False
