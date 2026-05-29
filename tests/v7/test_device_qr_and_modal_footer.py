"""M46 — Hide ops-controls footer in embed mode + device QR in
encounter cards + device QRs on the M41 print sheet.

Three things verified:

1. The M44 embed-mode CSS was missing a hide rule for the
   ``.ops-controls`` footer in `control_ops.html` (the Pause /
   Resume / Preview debrief / End scenario / Kill switch buttons +
   their explanation paragraph). Operators saw session-level
   controls that conflict with the M35 per-encounter Start/Pause/
   End in the parent encounter console's header.

2. The inline M45 device cards now show a QR per device so the
   operator can scan the cart's QR right from the encounter
   console (without reopening the Managed-devices modal where the
   mint-time QR lives).

3. The M41 QR print sheet renders a per-device QR section under
   each encounter's 4 station QRs — operators print one sheet and
   stick the QR on the actual hardware.
"""
from __future__ import annotations

from pathlib import Path

import pytest


TEST_PASSWORD = "test_passwd_xyz_8chars"
ENCOUNTER_JS = (
    Path(__file__).resolve().parents[2]
    / "portal" / "static" / "encounter_console.js"
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from portal import (
        auth, control_room, credentials, voices as _voices,
        debrief as debrief_mod, server as server_mod,
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
    monkeypatch.setattr(server_mod, "_anthropic_runtime_key", "")
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


def _start_room_with_pump(client):
    """Start a 1-encounter room and bind a pump device to it. Returns
    (room body, encounter_id, join_code, station_id)."""
    body = client.post("/api/room/start", json={
        "label": "M46",
        "encounters": [
            {"scenario_name": "Bed 1", "persona_id": "P-014",
             "patient_persona_id": "P-014", "personas": ["P-014"],
             "ehr_id": "helix"},
        ],
    }).json()
    eid  = body["encounters"][0]["encounter_id"]
    join = body["encounters"][0]["join_code"]
    sid  = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_iv", "device_model": "alaris",
              "label": "Bed 1 IV"},
    ).json()["station_id"]
    return body, eid, join, sid


# ── 1. Embed-mode CSS hides the .ops-controls footer ────────────────

def test_embed_mode_hides_ops_controls_footer(client) -> None:
    """The Pause / Resume / End scenario / Kill switch buttons + the
    explanation paragraph in `.ops-controls` were leaking through
    the M44 hide list. M46 explicitly hides them in embed mode."""
    body = client.post("/api/room/start", json={
        "label": "M46 footer hide",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    }).json()
    join = body["encounters"][0]["join_code"]
    r = client.get(f"/portal/control/ops?join={join}&embed=1")
    assert r.status_code == 200
    html = r.text
    # New explicit hide rule lands in the embed-mode <style> block.
    assert ".ops-controls" in html
    assert ".ops-controls + p" in html
    # The buttons themselves are still IN the page (the rule hides
    # them visually, doesn't remove them from the DOM — important so
    # tests don't have to wait on conditional template branches).
    assert 'id="btn-kill"' in html


def test_embed_mode_hide_block_unchanged_without_embed_flag(client) -> None:
    """Without ?embed=1 the .ops-controls hide rule isn't injected —
    the v6 single-patient ops view keeps showing its session
    controls (the legacy callsite still works exactly as before)."""
    body = client.post("/api/room/start", json={
        "label": "M46 v6 path",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    }).json()
    join = body["encounters"][0]["join_code"]
    r = client.get(f"/portal/control/ops?join={join}")
    html = r.text
    # The hide rule lives inside the {% if embed_mode %} block, so
    # without embed=1 there's no CSS rule by that name.
    assert ".ops-controls + p" not in html


# ── 2. Inline device cards render a QR per device ───────────────────

def test_inline_device_card_includes_qr_strip() -> None:
    """The M45 renderDeviceCard markup must include a device-card-qr
    block with an `<img>` pointing at /api/qr.svg?data=…"""
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    fn_idx = src.find("function renderDeviceCard")
    assert fn_idx >= 0
    # Window large enough to span renderDeviceCard's full body (QR
    # block lives near the end after the template-literal markup).
    body = src[fn_idx:fn_idx + 6000]
    # The QR strip is inside the card markup.
    assert "device-card-qr" in body
    assert "device-card-qr-img" in body
    assert "/api/qr.svg?data=" in body
    # The URL it encodes uses the device-join shape (host + /device/join?code=…&station=…).
    assert "/device/join?code=" in body
    assert "&station=" in body


def test_inline_device_card_qr_uses_encounter_join_code() -> None:
    """The QR URL must include the ENCOUNTER's join code (cfg.joinCode),
    not a hard-coded value. That's what makes the device join the
    right encounter when the operator scans."""
    src = ENCOUNTER_JS.read_text(encoding="utf-8")
    fn_idx = src.find("function renderDeviceCard")
    body = src[fn_idx:fn_idx + 6000]
    # cfg.joinCode is referenced when building deviceJoinUrl.
    assert "cfg.joinCode" in body
    assert "deviceJoinUrl" in body


# ── 3. M41 print sheet renders device QRs ───────────────────────────

def test_qr_print_renders_device_qr_per_encounter(client) -> None:
    """After a device is registered, the QR print sheet shows a
    `.device-qr-section` with that device's QR + URL."""
    _body, eid, join, sid = _start_room_with_pump(client)
    r = client.get("/portal/control/qr_print")
    assert r.status_code == 200
    html = r.text
    # Section anchor + title appear.
    assert "device-qr-section" in html
    assert "📟 Devices" in html or "Devices (1)" in html
    # Per-device label + sublabel.
    assert "Bed 1 IV" in html
    assert "pump_iv" in html
    assert "alaris" in html
    # QR image points at the device-join URL.
    assert f"/device/join?code={join}" in html
    assert f"station={sid}" in html
    # The plain-text URL appears under the QR for typed fallback.
    assert f"/device/join?code={join}" in html
    assert sid in html


def test_qr_print_omits_device_section_when_no_devices(client) -> None:
    """An encounter with no bound devices doesn't render an empty
    device QR section — the `{% if enc.devices %}` guard keeps the
    print sheet clean.  The class name `device-qr-section` still
    appears in the page's inline <style> block (CSS rule); the
    guard against false positives is checking for the actual
    `<h3 class="device-qr-section-title">` element rendering."""
    body = client.post("/api/room/start", json={
        "label": "M46 no devices",
        "encounters": [{"scenario_name": "Bed 1", "persona_id": "P-014",
                         "patient_persona_id": "P-014", "ehr_id": "helix"}],
    }).json()
    r = client.get("/portal/control/qr_print")
    html = r.text
    # No device QR section content. The `📟 Devices` marker only
    # appears inside the rendered template's `<h3>`, not in the
    # inline <style> block — so it's a clean signal for "section
    # was rendered" without false positives from the CSS class name.
    assert "📟 Devices" not in html


def test_qr_print_route_passes_devices_view_per_encounter(client) -> None:
    """The route now hydrates each encounter view with a `devices`
    list — verify the shape via a second device add. Two devices on
    bed 1 → both appear on the print sheet."""
    _body, eid, join, sid1 = _start_room_with_pump(client)
    sid2 = client.post(
        f"/api/device/register?join={join}",
        json={"device_kind": "pump_enteral", "device_model": "kangaroo_omni",
              "label": "Bed 1 enteral"},
    ).json()["station_id"]
    r = client.get("/portal/control/qr_print")
    html = r.text
    assert "Devices (2)" in html
    assert sid1 in html
    assert sid2 in html
    assert "Bed 1 IV" in html
    assert "Bed 1 enteral" in html
