"""M34 — Per-encounter instructor EHR launch.

The Per-Patient Console now carries a "📋 Open EHR (new window)"
button. It hits /portal/room/encounter/{id}/launch_ehr which
registers (or reuses) an instructor EHR station for that encounter
and redirects into the unified EHR bundle at /ehr/{join}/{station}.

This is the v7-aware twin of /portal/control/launch_ehr — that
v6-singleton route calls `control_session.get_active()`, which
returns None in a multi-encounter room and would dead-end.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import (
        auth, control_room, credentials, voices as _voices,
        debrief as debrief_mod,
    )
    sandbox_vault_dir = fake_home / ".medsim"
    sandbox_vault_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(credentials, "VAULT_DIR", sandbox_vault_dir)
    monkeypatch.setattr(credentials, "VAULT_PATH",
                         sandbox_vault_dir / "vault.enc")
    monkeypatch.setattr(_voices, "KEYFILE", tmp_path / "no-such.key")
    monkeypatch.setattr(_voices, "_runtime_key", "")
    sandbox_debriefs = tmp_path / "data" / "debriefs"
    monkeypatch.setattr(debrief_mod, "DEBRIEFS_DIR", sandbox_debriefs)
    monkeypatch.setattr(debrief_mod, "COHORT_DEBRIEFS_DIR",
                         sandbox_debriefs / "cohort")
    control_room._reset_for_tests()
    if not credentials.is_initialized():
        credentials.initialize(TEST_PASSWORD)
    vault = credentials.unlock(TEST_PASSWORD)
    vault.set("ANTHROPIC_API_KEY", "sk-ant-dummy")
    vault.set("ELEVENLABS_API_KEY", "")
    from portal import server
    from fastapi.testclient import TestClient
    with TestClient(server.app) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.issue_session_token(vault))
        yield c
    control_room._reset_for_tests()


def _start_two_encounter_room(client, with_ehr: bool = True) -> list[dict]:
    payload = {
        "label": "M34 launch_ehr",
        "encounters": [
            {"scenario_name": "Bed 1 — ICU",
             "persona_id": "P-014", "patient_persona_id": "P-014",
             **({"ehr_id": "helix"} if with_ehr else {})},
            {"scenario_name": "Bed 2 — Peds",
             "persona_id": "P-003", "patient_persona_id": "P-003",
             **({"ehr_id": "helix"} if with_ehr else {})},
        ],
    }
    r = client.post("/api/room/start", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["encounters"]


# ── Backend route tests ──────────────────────────────────────────────

def test_per_encounter_launch_ehr_redirects_to_chart(client) -> None:
    """GET /portal/room/encounter/{id}/launch_ehr registers a control-
    room EHR station and 303s into /ehr/{join_code}/{station_id}."""
    encs = _start_two_encounter_room(client)
    eid = encs[0]["encounter_id"]
    join = encs[0]["join_code"]
    r = client.get(f"/portal/room/encounter/{eid}/launch_ehr",
                   follow_redirects=False)
    assert r.status_code == 303, r.text
    loc = r.headers["location"]
    assert loc.startswith(f"/ehr/{join}/"), (
        f"Expected redirect into /ehr/{join}/<station>, got {loc!r}")
    # The station segment is non-empty.
    station = loc.split("/")[-1]
    assert station and station.startswith("ES-")


def test_per_encounter_launch_ehr_post_returns_url_json(client) -> None:
    """POST flavor returns JSON {ok, url, ehr_id, station_id,
    encounter_id, reused} so programmatic callers can stitch."""
    encs = _start_two_encounter_room(client)
    eid = encs[0]["encounter_id"]
    join = encs[0]["join_code"]
    r = client.post(f"/portal/room/encounter/{eid}/launch_ehr")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["url"].startswith(f"/ehr/{join}/")
    assert body["ehr_id"] == "helix"
    assert body["encounter_id"] == eid
    assert body["station_id"].startswith("ES-")
    assert body["reused"] is False


def test_per_encounter_launch_ehr_reuses_station_on_repeat(client) -> None:
    """A repeat launch returns the same station id (avoids piling up
    instructor stations on every click). `reused` flips to True."""
    encs = _start_two_encounter_room(client)
    eid = encs[0]["encounter_id"]
    first  = client.post(f"/portal/room/encounter/{eid}/launch_ehr").json()
    second = client.post(f"/portal/room/encounter/{eid}/launch_ehr").json()
    assert first["station_id"] == second["station_id"], (
        "Repeat launch should reuse the same control-room EHR station.")
    assert second["reused"] is True


def test_per_encounter_launch_ehr_no_ehr_redirects_to_console(client) -> None:
    """If an encounter has no EHR configured, the GET form sends the
    instructor back to the console with an `?ehr=unconfigured` hint
    (the POST form raises 409 instead)."""
    encs = _start_two_encounter_room(client, with_ehr=False)
    eid = encs[0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}/launch_ehr",
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(
        f"/portal/room/encounter/{eid}?ehr=unconfigured")
    r = client.post(f"/portal/room/encounter/{eid}/launch_ehr")
    assert r.status_code == 409


def test_per_encounter_launch_ehr_unknown_encounter_returns_404(client) -> None:
    _start_two_encounter_room(client)
    r = client.get("/portal/room/encounter/ENC-bogus/launch_ehr",
                   follow_redirects=False)
    assert r.status_code == 404
    r = client.post("/portal/room/encounter/ENC-bogus/launch_ehr")
    assert r.status_code == 404


# ── Console UI tests ─────────────────────────────────────────────────

def test_console_header_renders_open_ehr_button(client) -> None:
    """The Per-Patient Console <header> has a green primary action
    linking to the per-encounter launch_ehr route with
    `target="_blank"` so it opens in a new window."""
    encs = _start_two_encounter_room(client)
    eid = encs[0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert "btn-launch-ehr" in html
    assert f'href="/portal/room/encounter/{eid}/launch_ehr"' in html
    assert 'target="_blank"' in html
    # Mentions the EHR id (helix) so the instructor knows which
    # chart they're opening.
    assert "Open EHR (helix)" in html


def test_console_header_shows_disabled_state_when_no_ehr(client) -> None:
    encs = _start_two_encounter_room(client, with_ehr=False)
    eid = encs[0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    assert r.status_code == 200
    html = r.text
    assert "btn-launch-ehr" not in html
    assert "header-action-disabled" in html
    assert "No EHR configured" in html


def test_qr_card_shows_open_ehr_on_this_device_link(client) -> None:
    """Inside the QR-codes card, under the EHR station cell, there's
    a 'Open EHR on this device' link so the instructor can skip the
    QR entirely."""
    encs = _start_two_encounter_room(client)
    eid = encs[0]["encounter_id"]
    r = client.get(f"/portal/room/encounter/{eid}")
    html = r.text
    assert "qr-launch-here" in html
    assert "Open EHR on this device" in html
