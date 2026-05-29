"""V5 — Playwright UI tests for the functional EHR engine.

Proves the rebuilt medical record actually WORKS in a real browser:
the scenario-seeded patient renders, a note can be written + signed and
survives a reload (i.e. it persisted to the chart-event DB), an order
places, and vitals record into the flowsheet.

A real uvicorn server is started in a subprocess with a sandboxed HOME
so it gets a throwaway vault + ehr.db and never touches the operator's
real data.

Requires Playwright + Chromium (installed in Phase 0). If Playwright is
unavailable the module is skipped rather than failing the suite.
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

PROJECT = Path(__file__).resolve().parent.parent
PASSWORD = "medsim-v5-ui-test"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """A live uvicorn server with a sandboxed HOME (throwaway vault + DB)."""
    home = tmp_path_factory.mktemp("medsim_home")
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


def _login_and_open_ehr(page, live_server):
    """Initialize the vault, set a dummy API key, start a scenario, and
    return the launched EHR URL."""
    # Fresh sandbox → the login page shows the initialize form.
    page.goto(live_server + "/login")
    page.fill('input[name=password]', PASSWORD)
    page.fill('input[name=confirm]', PASSWORD)
    page.click('button:has-text("Initialize vault")')
    page.wait_for_url("**/portal/home")

    # control_start requires an Anthropic key in the vault.
    page.request.post(live_server + "/portal/credentials", form={
        "key": "ANTHROPIC_API_KEY", "value": "sk-ant-dummy-ui-test"})

    # Start a scenario (Mrs. Kowalski + diabetes module, Helix EHR).
    r = page.request.post(live_server + "/portal/control/start", form={
        "scenario_name": "UI test — DKA",
        "scenario_notes": "",
        "scenario_text": "78yo woman, type 2 diabetic, glucose 480, confused.",
        "program_id": "", "week": "",
        "modules": "M22", "personas": "P-013", "ehr_id": "helix",
    })
    assert r.ok, r.text()

    # Launch the EHR on this device → JSON {url}.
    r = page.request.post(live_server + "/portal/control/launch_ehr")
    assert r.ok, r.text()
    return live_server + r.json()["url"]


def test_functional_ehr_end_to_end(live_server, browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    ehr_url = _login_and_open_ehr(page, live_server)

    # ── Open the EHR ───────────────────────────────────────────────
    page.goto(ehr_url)
    page.wait_for_selector("text=Chart Review", timeout=8000)  # Helix tab label

    # The patient banner shows the SCENARIO persona — not a mockup name.
    assert page.locator("text=Mrs. Kowalski").count() > 0, \
        "EHR banner does not show the scenario patient"

    # ── Write + sign a note ────────────────────────────────────────
    page.click("text=Notes")
    page.click("button:has-text('New note')")
    page.fill("textarea", "SBAR: glucose 480, started insulin protocol per order.")
    page.click("button:has-text('Sign & file')")
    page.wait_for_selector("text=Note signed.", timeout=5000)

    # ── Reload — the note must survive (it persisted to the DB) ─────
    page.reload()
    page.wait_for_selector("text=Chart Review", timeout=8000)
    page.click("text=Notes")
    assert page.locator("text=insulin protocol per order").count() > 0, \
        "the signed note did not survive a reload — not persisted"

    # ── Record vitals → flowsheet updates ──────────────────────────
    page.click("text=Vitals")
    inputs = page.locator("section:has-text('Record a vitals set') input")
    inputs.nth(1).fill("104")   # HR
    inputs.nth(3).fill("88/52") # BP
    page.click("button:has-text('Record vitals')")
    page.wait_for_selector("text=Vitals recorded.", timeout=5000)
    assert page.locator("td:has-text('104')").count() > 0, \
        "recorded vitals did not appear in the flowsheet"

    # ── Place an order ─────────────────────────────────────────────
    page.click("text=CPOE")  # Helix label for the orders tab
    page.wait_for_selector("input[placeholder='Search orders…']", timeout=5000)
    page.fill("input[placeholder='Search orders…']", "BMP")
    page.click("button:has-text('Add')")
    page.fill("input[placeholder*='Rationale']", "Recheck given hyperglycemia.")
    page.click("button:has-text('Sign & send')")
    page.wait_for_selector("text=Order placed.", timeout=5000)
    assert page.locator("text=BMP").count() > 0

    # ── A medication ordered in CPOE must appear on the MAR ────────
    page.fill("input[placeholder='Search orders…']", "CEFTRIAXONE")
    page.click("button:has-text('Add')")
    page.fill("input[placeholder*='Rationale']", "Empiric antibiotic coverage.")
    page.click("button:has-text('Sign & send')")
    page.wait_for_selector("text=Order placed.", timeout=5000)

    page.click("text=MAR")
    mar = page.locator("section:has-text('Medication Administration Record')")
    page.wait_for_selector("text=Ceftriaxone 1 g IV", timeout=5000)
    assert mar.locator("text=Ceftriaxone 1 g IV").count() > 0, \
        "medication ordered in CPOE did not appear on the MAR"
    assert mar.locator("text=ordered").count() > 0, \
        "ordered medication not flagged on the MAR"
    # And it can be administered from the MAR.
    page.locator("button:has-text('Administer')").first.click()
    page.wait_for_selector("text=Medication administered.", timeout=5000)

    page.click("text=CPOE")

    # ── Add a custom supply to the master catalog ──────────────────
    page.fill("input[placeholder='e.g. WOUND VAC KIT']", "PW CUSTOM SUPPLY")
    page.fill("input[placeholder='Human-readable description']",
              "Playwright custom catalog item")
    page.click("button:has-text('Add to catalog')")
    page.wait_for_selector("text=Added to the master order catalog.", timeout=5000)
    # It is now an orderable catalog item (the row shows the label).
    page.fill("input[placeholder='Search orders…']", "PW CUSTOM")
    assert page.locator("text=Playwright custom catalog item").count() > 0, \
        "custom catalog item not orderable after adding"

    ctx.close()


def test_demo_mode_renders_without_a_session(live_server, browser):
    """The wizard-preview demo route renders the engine with sample data
    and no backend session."""
    ctx = browser.new_context()
    page = ctx.new_page()
    # Need an operator cookie for the demo route.
    page.goto(live_server + "/login")
    if page.locator('input[name=confirm]').count() > 0:
        page.fill('input[name=password]', PASSWORD)
        page.fill('input[name=confirm]', PASSWORD)
        page.click('button:has-text("Initialize vault")')
    else:
        page.fill('input[name=password]', PASSWORD)
        page.click('button:has-text("Unlock")')
    page.wait_for_url("**/portal/home")

    page.goto(live_server + "/ehr/demo/meridian")
    page.wait_for_selector("text=Chart", timeout=8000)
    assert page.locator("text=DEMO").count() > 0, "demo banner missing"
    ctx.close()
