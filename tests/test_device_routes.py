"""V6 — operator-side HTTP routes for the device subsystem.

Covers: auth gating (anonymous = 401), mint flow returns station_id +
QR + join URL, assign + reassign, alarm inject, roster lists every
joined station, models endpoint exposes all three reference devices,
device_join + device_app shells render with the right data.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Use the same shared password as the v5 voice/e2e tests so the vault on
# disk stays compatible if those tests have already initialised it.
TEST_PASSWORD = "test_passwd_xyz_8chars"


def _ensure_vault_for_password():
    """Initialise the on-disk vault with TEST_PASSWORD if it isn't already."""
    from portal import credentials
    vault_path = Path.home() / ".medsim" / "vault.enc"
    if vault_path.exists():
        try:
            credentials.unlock(TEST_PASSWORD)
            return
        except ValueError:
            # Vault is locked with some other password (probably a leftover
            # from an aborted test run). Remove + reinit.
            vault_path.unlink()
    credentials.initialize(TEST_PASSWORD)


@pytest.fixture
def client():
    _ensure_vault_for_password()
    from portal import server, control_session
    c = TestClient(server.app)
    c.post("/login", data={"password": TEST_PASSWORD})
    sess = control_session.create_session(
        scenario_name="dev-routes-test",
        selected_personas=["P-001"], selected_modules=[], api_key="dummy")
    c._session = sess
    yield c
    control_session.end_active()


def test_models_endpoint_lists_three_reference_devices(client):
    r = client.get("/api/device/models")
    assert r.status_code == 200
    models = r.json()
    assert "alaris"        in models["pump_iv"]
    assert "kangaroo_omni" in models["pump_enteral"]
    assert "pyxis"         in models["cabinet"]


def test_models_filtered_by_declared_device_kind(client):
    """Regression: bootstrap 500 KeyError 'channels' — happened when an
    enteral model was offered as an IV pump (both share pumps/ folder),
    so an IV engine loaded an enteral spec with no 'channels' key.
    The registry must now filter by spec.device_kind."""
    r = client.get("/api/device/models")
    models = r.json()
    # IV pump list must NOT include the enteral model
    assert "kangaroo_omni" not in models["pump_iv"]
    # Enteral list must NOT include the IV model
    assert "alaris"        not in models["pump_enteral"]
    # Cabinet list must NOT include either pump
    assert "alaris"        not in models["cabinet"]
    assert "kangaroo_omni" not in models["cabinet"]


def test_anonymous_cannot_register(client):
    # Use a fresh client with no auth cookie.
    raw = TestClient(client.app)
    r = raw.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris", "label": "X"})
    assert r.status_code == 401


def test_register_returns_station_qr_and_join_url(client):
    r = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "Bed 3 IV"})
    assert r.status_code == 200
    j = r.json()
    assert j["station_id"].startswith("dev_")
    assert "/device/join" in j["join_url"]
    assert "<svg" in j["qr_svg"]
    assert client._session.join_code in j["join_url"]


def test_register_rejects_unknown_model(client):
    r = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "doesnotexist",
        "label": "X"})
    assert r.status_code == 400


def test_assign_then_inject_flow(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "Bed 3"}).json()["station_id"]
    assert client.post(f"/api/device/{sid}/assign",
                        json={"character_id": "P-001"}).status_code == 200
    r = client.post(f"/api/device/{sid}/inject",
                     json={"tone": "air_in_line"})
    assert r.status_code == 200
    tones = [a["tone"] for a in r.json()["state"]["active_alarms"]]
    assert "air_in_line" in tones


def test_inject_rejects_unknown_tone(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "X"}).json()["station_id"]
    r = client.post(f"/api/device/{sid}/inject", json={"tone": "nope"})
    assert r.status_code == 400


def test_inject_validates_tone_against_device_kind(client):
    # cabinet alerts don't include 'air_in_line' (that's a pump tone)
    sid = client.post("/api/device/register", json={
        "device_kind": "cabinet", "device_model": "pyxis",
        "label": "Cart A"}).json()["station_id"]
    r = client.post(f"/api/device/{sid}/inject", json={"tone": "air_in_line"})
    assert r.status_code == 400


def test_roster_lists_every_minted_device(client):
    for kind, model, label in [
        ("pump_iv",      "alaris",        "Bed 3"),
        ("pump_enteral", "kangaroo_omni", "Bed 4"),
        ("cabinet",      "pyxis",         "Cart A"),
    ]:
        client.post("/api/device/register", json={
            "device_kind": kind, "device_model": model, "label": label})
    r = client.get("/api/device/roster")
    assert r.status_code == 200
    stations = r.json()["stations"]
    assert len(stations) == 3
    models = {s["device_model"] for s in stations}
    assert models == {"alaris", "kangaroo_omni", "pyxis"}


def test_device_join_landing_renders_with_station_data(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "cabinet", "device_model": "pyxis",
        "label": "Cart A"}).json()["station_id"]
    r = client.get(f"/device/join?code={client._session.join_code}&station={sid}")
    assert r.status_code == 200
    assert "Cart A" in r.text
    assert "/static/devices/manifest.json" in r.text
    assert "Add to Home Screen" in r.text   # A2HS hint


def test_device_app_shell_loads_bundle(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "Bed 3"}).json()["station_id"]
    r = client.get(f"/device/{client._session.join_code}/{sid}")
    assert r.status_code == 200
    assert "/static/devices/device_app.js" in r.text
    assert sid in r.text


def test_bootstrap_returns_spec_skin_audio_state(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "X"}).json()["station_id"]
    r = client.get(f"/api/device/{sid}/bootstrap")
    assert r.status_code == 200
    b = r.json()
    assert b["spec"]["device_model"] == "alaris"
    assert "<svg" in b["skin_svg"]
    assert "air_in_line" in b["audio_urls"]
    assert b["state"]["screen"] == "off"
    assert b["session_state"] in ("configured", "running")


def test_assignment_reflected_in_roster(client):
    sid = client.post("/api/device/register", json={
        "device_kind": "pump_iv", "device_model": "alaris",
        "label": "Bed 3"}).json()["station_id"]
    client.post(f"/api/device/{sid}/assign", json={"character_id": "P-001"})
    stations = client.get("/api/device/roster").json()["stations"]
    me = next(s for s in stations if s["station_id"] == sid)
    assert me["character_id"] == "P-001"
    # Reassign
    client.post(f"/api/device/{sid}/assign", json={"character_id": "P-002"})
    stations = client.get("/api/device/roster").json()["stations"]
    me = next(s for s in stations if s["station_id"] == sid)
    assert me["character_id"] == "P-002"


# ── /d QR redirector (rewritten 2026-06-10: same-scheme redirect, no Chrome bounce) ──

def test_qr_redirector_redirects_same_origin_relative(client):
    """The V6 version bounced to a hard-coded http:// URL (dead on the https-only portal)
    via a googlechrome:// handoff (dead on iPads without Chrome). It must now be a plain
    RELATIVE redirect — scheme/host/port preserved by construction on any platform."""
    r = client.get("/d?c=ABC123&s=station-1", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert loc == "/device/join?code=ABC123&station=station-1"
    assert "googlechrome" not in loc and "http://" not in loc


def test_qr_redirector_sanitizes_inputs(client):
    r = client.get("/d?c=AB%20<x>&s=st/../etc", follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert "<" not in loc and ".." not in loc and "/etc" not in loc
