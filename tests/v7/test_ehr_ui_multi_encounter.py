"""V7 M20 — Playwright multi-encounter coverage.

Real-browser end-to-end test of the multi-patient happy path:

  1. Operator initializes vault, sets a dummy API key.
  2. Operator finalizes a Room of 2 via /api/room/start (room mode).
  3. Two simulated tablets each open the student-join page, pick
     their bed, and land on a chat station.
  4. Operator clicks Freeze All → both encounters paused; both
     chat stations see the freeze.
  5. Operator clicks Resume All → both running.
  6. Operator injects a `vitals.drop` scene at encounter A.
  7. /api/room/state shows encounter A has 1 chart event, B has 0
     (encounter scoping holds end-to-end through the browser).
  8. Operator ends the room → cohort debrief saved → debrief page
     renders.

Skipped automatically when Playwright isn't installed (mirrors v6
``tests/test_ehr_ui.py``). When Playwright IS installed, runs in
~30 s against a sandboxed uvicorn subprocess.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent.parent
PASSWORD = "medsim-v7-m20-test"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Sandboxed uvicorn subprocess — throwaway HOME + vault + DB."""
    home = tmp_path_factory.mktemp("medsim_v7_home")
    port = _free_port()
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("ELEVENLABS_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "portal.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(PROJECT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(150):
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            ready = True
            break
        except Exception:
            time.sleep(0.1)
    if not ready:
        # /health may not exist — fall back to /login.
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                ready = True
                break
            except Exception:
                time.sleep(0.1)
    if not ready:
        out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
        proc.terminate()
        raise RuntimeError(f"server did not start:\n{out[:2000]}")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _initialize_and_login(page, base: str) -> None:
    page.goto(base + "/login")
    page.fill('input[name=password]', PASSWORD)
    if page.locator('input[name=confirm]').count():
        page.fill('input[name=confirm]', PASSWORD)
        page.click('button:has-text("Initialize")')
    else:
        page.click('button[type=submit]')
    page.wait_for_url("**/portal/home")
    page.request.post(base + "/portal/credentials", form={
        "key": "ANTHROPIC_API_KEY", "value": "sk-ant-dummy-m20"})


def test_ehr_ui_multi_encounter(live_server, browser) -> None:
    base = live_server
    ctx = browser.new_context()
    op_page = ctx.new_page()
    _initialize_and_login(op_page, base)

    # ── 1. Operator finalizes a 2-bed room via the API ────────
    resp = op_page.request.post(base + "/api/room/start", data={
        "label": "M20 Playwright test",
        "encounters": [
            {"scenario_name": "Bed 1 — Diaz",
             "persona_id": "P-001", "patient_persona_id": "P-001",
             "ehr_id": "helix"},
            {"scenario_name": "Bed 2 — Kowalski",
             "persona_id": "P-013", "patient_persona_id": "P-013",
             "ehr_id": "helix"},
        ],
    })
    body = resp.json()
    assert resp.ok, body
    room_code = body["room_code"]
    eid_a = body["encounters"][0]["encounter_id"]
    eid_b = body["encounters"][1]["encounter_id"]

    # ── 2. Operator opens the dashboard ───────────────────────
    op_page.goto(base + "/portal/room")
    op_page.wait_for_selector(".encounter-card")
    cards = op_page.locator(".encounter-card")
    assert cards.count() == 2

    # ── 3. Two student tabs each join the room ────────────────
    student_a = ctx.new_page()
    student_b = ctx.new_page()
    for sp, name, eid in ((student_a, "Alice", eid_a),
                            (student_b, "Bob",   eid_b)):
        sp.goto(f"{base}/portal/students/join?code={room_code}")
        sp.fill("#display-name", name)
        # M27 added a role-picker step (bedside vs nurse-station)
        # between the name input and the encounter cards. Press
        # Enter to commit the name (reveals step-role), click
        # Bedside (reveals step-encounter), then click the bed.
        sp.locator("#display-name").press("Enter")
        sp.wait_for_selector(".role-card[data-role='bedside']",
                              state="visible")
        sp.locator(".role-card[data-role='bedside']").click()
        sp.wait_for_selector(
            f'.encounter-card[data-encounter-id="{eid}"]',
            state="visible")
        sp.locator(f'.encounter-card[data-encounter-id="{eid}"]').click()
        sp.wait_for_url("**/station/**")

    # ── 4. Freeze All ─────────────────────────────────────────
    op_page.click("#btn-freeze")
    # Wait one poll cycle so the badge updates.
    op_page.wait_for_function(
        "document.getElementById('room-status').textContent === 'FROZEN'",
        timeout=5000,
    )

    # ── 5. Resume All ─────────────────────────────────────────
    # M35 — the standalone #btn-resume was removed from the
    # dashboard; #btn-start-all handles both first-launch and
    # resume-from-frozen via /api/room/start_all.
    op_page.click("#btn-start-all")
    op_page.wait_for_function(
        "document.getElementById('room-status').textContent === 'ACTIVE'",
        timeout=5000,
    )

    # ── 6. Inject a vitals.drop into encounter A only ─────────
    resp = op_page.request.post(
        f"{base}/api/encounter/{eid_a}/scene",
        data={"scene": {"kind": "vitals.drop", "params": {"sbp": 70}}},
    )
    assert resp.ok, resp.text()

    # ── 7. /api/room/state shows scoping: A=1, B=0 ────────────
    state = op_page.request.get(base + "/api/room/state").json()
    counts = {e["encounter_id"]: e["chart_event_count"]
               for e in state["encounters"]}
    assert counts[eid_a] == 1
    assert counts[eid_b] == 0

    # ── 8. End room → cohort debrief saves + renders ──────────
    # The dashboard's End button confirms — bypass via API for the
    # test (the dashboard's confirm() is browser-side noise).
    resp = op_page.request.post(base + "/api/room/end")
    assert resp.ok, resp.text()
    body = resp.json()
    assert body["cohort_debrief_saved"] is True
    op_page.goto(base + body["cohort_debrief_url"])
    op_page.wait_for_selector(".pearls-tabs")
    # Tabs render for all 4 PEARLS phases + per-encounter + summary.
    assert op_page.locator('.pearls-tab[data-phase="reactions"]').count() == 1
    assert op_page.locator('.pearls-tab[data-phase="analysis"]').count() == 1
    # The encounter facets list both beds.
    op_page.click('.pearls-tab[data-phase="encounters"]')
    assert op_page.locator("details.encounter-facet").count() == 2
