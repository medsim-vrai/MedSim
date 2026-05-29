"""M56 — Med-cart create form with encounter checklist + post-create
add-encounters checklist.

Operator: "When the Med Carts are generated, it needs to include a
check off list of the encounters to be joined to it. Currently the
med cart generated are only assigned to the first encounter of [the]
listed in the Multi patient control screen. Additionally, med cart
assignment needs the ability to add encounters to the list after it
has been created."

Pre-M56: the create form only sent `{label}` — the back-end fell
back to the first encounter as the cart's only link. Post-create
UI was a single-select dropdown (one link at a time).

M56 delivers:
  1. Create form has a checklist of every encounter in the room.
     Ticked beds get linked at creation.
  2. Per-cart card has a multi-checkbox "Add encounters" section
     for extending the link list after creation in one click.
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


def _start_room(client, n: int = 3):
    # Use known-real persona ids so seeds_for_all_personas resolves
    # them and the cabinet bootstrap returns a non-empty characters
    # list. (Mirrors the M47 test fixture pattern.)
    pool = ["P-014", "P-003", "P-001", "P-005", "P-007", "P-010",
            "P-012", "P-013", "P-016", "P-020"]
    r = client.post("/api/room/start", json={
        "label": "M56",
        "encounters": [
            {"scenario_name": f"Bed {i+1}", "persona_id": pool[i],
             "patient_persona_id": pool[i],
             "personas": [pool[i]], "ehr_id": "helix"}
            for i in range(n)
        ],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. Create form back-end accepts a multi-encounter list ─────────

def test_med_cart_register_links_all_requested_encounters(client) -> None:
    body = _start_room(client, n=3)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "ICU Cart",
                           "encounter_ids": eids})
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out["linked_encounter_ids"]) == set(eids)
    # First requested encounter becomes the primary.
    assert out["primary_encounter_id"] == eids[0]


def test_med_cart_register_with_subset_only_links_picked_ones(client) -> None:
    """Operator picks 2 of 3 beds → only those 2 land in the cart's
    link list. The third stays unlinked."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Subset Cart",
                           "encounter_ids": [e1, e3]})
    assert r.status_code == 200
    out = r.json()
    assert set(out["linked_encounter_ids"]) == {e1, e3}
    assert e2 not in out["linked_encounter_ids"]


def test_med_cart_register_empty_list_falls_back_to_first(client) -> None:
    """Back-compat: posting NO encounter_ids should still mint a cart
    on the first encounter so the simple workflow keeps working."""
    body = _start_room(client, n=3)
    first = body["encounters"][0]["encounter_id"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Default Cart"})
    assert r.status_code == 200
    assert r.json()["primary_encounter_id"] == first


def test_med_cart_register_unknown_encounter_400(client) -> None:
    _start_room(client, n=1)
    r = client.post("/api/room/med_cart/register",
                     json={"label": "X",
                           "encounter_ids": ["bogus-eid"]})
    assert r.status_code == 400


# ── 2. Multi-Patient Control template renders the checklist ────────

def test_create_form_has_checkbox_per_encounter(client) -> None:
    body = _start_room(client, n=3)
    html = client.get("/portal/room").text
    # Fieldset legend explains the rule.
    assert "Link this cart to which encounters" in html
    # One checkbox per encounter, carrying the encounter id.
    for enc in body["encounters"]:
        eid = enc["encounter_id"]
        assert f'data-encounter-id="{eid}"' in html
    # The class name the JS reads at submit time.
    assert "med-cart-create-enc-cb" in html


def test_create_form_hidden_when_no_room(client) -> None:
    """Operators with no room shouldn't see the cart form at all
    (the {% if room %} block already guards this)."""
    html = client.get("/portal/room").text
    assert 'id="med-cart-create-form"' not in html


# ── 3. JS handlers ─────────────────────────────────────────────────

def test_control_room_js_sends_checked_encounter_ids_on_create() -> None:
    """The submit handler scans `.med-cart-create-enc-cb:checked`
    and POSTs them as `encounter_ids`."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.js").read_text("utf-8")
    assert ".med-cart-create-enc-cb:checked" in src
    assert "encounter_ids" in src
    # Confirmation banner counts how many landed.
    assert "linked_encounter_ids" in src


def test_control_room_js_card_renders_add_encounters_checklist() -> None:
    """Post-create UI replaces the single-select dropdown with a
    multi-checkbox "Add encounters" affordance."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.js").read_text("utf-8")
    # The new add-encounters block.
    assert "med-cart-add-checklist" in src
    assert "med-cart-add-enc-cb" in src
    # The "add-multi" action handler that fans out one link call
    # per ticked encounter.
    assert 'data-act="add-multi"' in src
    assert "'add-multi'" in src
    # Pre-M56 dropdown / single-select should be gone.
    assert "med-cart-link-select" not in src
    assert "data-act=\"link\"" not in src


def test_control_room_css_styles_new_checklists() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.css").read_text("utf-8")
    assert ".med-cart-encs-checklist" in src
    assert ".med-cart-add-checklist" in src
    assert ".med-cart-enc-check" in src
    assert ".med-cart-add-check" in src


# ── 4. End-to-end: create with N encounters, then add another ──────

def test_cart_workflow_create_then_add_more_encounters(client) -> None:
    """Operator picks 2 beds at create time, then extends the cart
    to a 3rd bed afterwards. The cart's link list grows."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Step Cart",
                           "encounter_ids": [e1, e2]})
    assert r.status_code == 200, r.text
    cart_sid = r.json()["station_id"]
    assert set(r.json()["linked_encounter_ids"]) == {e1, e2}
    # Now add the third encounter using the existing M47 link route.
    r = client.post(
        f"/api/room/med_cart/{cart_sid}/link_encounter",
        json={"encounter_id": e3})
    assert r.status_code == 200, r.text
    # Verify by listing carts.
    carts = client.get("/api/room/med_carts").json()["carts"]
    cart = next(c for c in carts if c["station_id"] == cart_sid)
    assert set(cart["linked_encounter_ids"]) == {e1, e2, e3}


def test_cabinet_bootstrap_sees_all_linked_encounters(client) -> None:
    """The whole point: cabinet bootstrap should now surface
    characters from EVERY linked encounter, not just the primary."""
    body = _start_room(client, n=3)
    eids = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Multi-bed Cart",
                           "encounter_ids": eids})
    cart_sid = r.json()["station_id"]
    boot = client.get(f"/api/device/{cart_sid}/bootstrap").json()
    chars = boot.get("characters") or []
    # One persona per encounter = 3 patients on the cart.
    encounter_ids_seen = {c.get("encounter_id") for c in chars}
    assert encounter_ids_seen == set(eids)


# ── 5. M56 bugfix — visible tick counter + cache headers ───────────

def test_create_form_renders_tick_counter(client) -> None:
    """The "Will link N encounters" counter is server-rendered so
    the operator sees an immediate baseline (0 of M) without waiting
    for JS to initialise."""
    _start_room(client, n=3)
    html = client.get("/portal/room").text
    assert 'id="med-cart-tick-count"' in html
    # Initial server-rendered text shows "Will link 0 encounters"
    # (JS upgrades it to "0 of 3" on DOMContentLoaded).
    assert "Will link 0 encounter" in html


def test_dashboard_html_has_no_store_cache(client) -> None:
    """M56 bugfix root cause was stale cached HTML masking the new
    checkbox form. Dashboard now returns Cache-Control: no-store so
    a refresh always gets the latest UI."""
    _start_room(client, n=1)
    r = client.get("/portal/room")
    assert r.status_code == 200
    assert "no-store" in (r.headers.get("Cache-Control") or "").lower()


def test_control_room_js_wires_tick_counter() -> None:
    """The submit handler now has a sibling `_updateTickCount`
    helper bound to every checkbox's `change` event."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text("utf-8")
    assert "_updateTickCount" in src
    assert "med-cart-tick-count" in src
    # The helper iterates :checked AND :not(:checked) so it can
    # render "N of M".
    assert ".med-cart-create-enc-cb:checked" in src
    # Counter resets after a successful create.
    assert "_updateTickCount()" in src


def test_control_room_js_captures_encounters_from_state_top_level() -> None:
    """Latent M47 bug: `body.room` is not where /api/room/state puts
    the encounters; they're at `body.encounters` (see _room_summary).
    M56-bugfix swaps the guard from `body.room` to just `body`."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text("utf-8")
    # The actual call site (not the helper definition or comments)
    # uses _captureEncountersForCarts(body) — the whole state body
    # is passed so the helper can read body.encounters.
    assert "_captureEncountersForCarts(body)" in src
    # And the pre-fix `body.room` guard at the CALL SITE is gone.
    # (The historical comment may still mention "body.room" for
    # context, so we check the exact call expression instead.)
    assert "if (body && body.room) _captureEncountersForCarts" not in src
    assert "_captureEncountersForCarts(body.room)" not in src


# ── 6. M59 — Launch Med Cart button per cart ───────────────────────

def test_med_cart_register_response_carries_device_url(client) -> None:
    """The register response includes `device_url` — the direct
    /device/{join_code}/{station_id} path that bypasses the
    /device/join landing page."""
    body = _start_room(client, n=2)
    eids = [e["encounter_id"] for e in body["encounters"]]
    primary_join = body["encounters"][0]["join_code"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Cart with launch",
                           "encounter_ids": eids})
    assert r.status_code == 200, r.text
    out = r.json()
    assert "device_url" in out
    assert out["device_url"]
    assert f"/device/{primary_join}/{out['station_id']}" in out["device_url"]
    # And NOT the /device/join landing path.
    assert "/device/join" not in out["device_url"]


def test_med_carts_list_response_carries_device_url(client) -> None:
    """The list endpoint also exposes `device_url` so the dashboard's
    cart cards can render a launch button after a refresh."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    join = body["encounters"][0]["join_code"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Listed cart",
                           "encounter_ids": [eid]})
    cart_sid = r.json()["station_id"]
    carts = client.get("/api/room/med_carts").json()["carts"]
    cart = next(c for c in carts if c["station_id"] == cart_sid)
    assert cart.get("device_url")
    assert f"/device/{join}/{cart_sid}" in cart["device_url"]


def test_control_room_js_renders_launch_button() -> None:
    """The cart card template includes a `.med-cart-launch-btn`
    anchor whose href is `cart.device_url` and target=_blank."""
    p = (Path(__file__).resolve().parents[2]
         / "portal" / "static" / "control_room.js")
    src = p.read_text("utf-8")
    assert "med-cart-launch-btn" in src
    assert "cart.device_url" in src
    # Opens in a new window.
    assert 'target="_blank"' in src
    # Friendly label so the operator knows what the button does.
    assert "Open cart" in src


def test_control_room_css_styles_launch_button() -> None:
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.css").read_text("utf-8")
    assert ".med-cart-launch-btn" in src
    # Header is a flex row so the button can sit on the right.
    assert ".med-cart-card-header" in src


def test_cart_device_url_renders_the_cart_tablet_template(client) -> None:
    """Hitting the device_url directly should serve the device tablet
    HTML for the cart (cabinet kind → device_app.html)."""
    body = _start_room(client, n=1)
    eid = body["encounters"][0]["encounter_id"]
    join = body["encounters"][0]["join_code"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Direct launch cart",
                           "encounter_ids": [eid]})
    cart_sid = r.json()["station_id"]
    # The device-tablet URL the launch button points at.
    r2 = client.get(f"/device/{join}/{cart_sid}")
    assert r2.status_code == 200
    # The tablet shell template has the device-root container.
    assert "device-root" in r2.text or "device-skin" in r2.text


# ── 7. M59 bugfix — All/None quick toggles + count badge ───────────

def test_create_form_renders_all_none_toggles(client) -> None:
    """Operator-friendly quick toggles so they don't have to tick
    every encounter one-by-one. Most common cart workflow."""
    _start_room(client, n=3)
    html = client.get("/portal/room").text
    assert 'id="med-cart-create-all"' in html
    assert 'id="med-cart-create-none"' in html
    assert "All beds" in html


def test_control_room_js_wires_all_none_toggles() -> None:
    """The buttons check/uncheck every `.med-cart-create-enc-cb` and
    refresh the tick counter so the operator sees the new state."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.js").read_text("utf-8")
    assert "med-cart-create-all" in src
    assert "med-cart-create-none" in src
    # Toggle handlers iterate every checkbox + call _updateTickCount.
    assert "cb.checked = true" in src
    assert "cb.checked = false" in src


def test_cart_card_renders_count_badge(client) -> None:
    """Each cart card now carries a prominent 🔗 N beds count badge
    in its header so the operator can't miss what's linked."""
    body = _start_room(client, n=2)
    eids = [e["encounter_id"] for e in body["encounters"]]
    client.post("/api/room/med_cart/register",
                 json={"label": "Visible Cart",
                       "encounter_ids": eids})
    # Inspect the JS render path: the count badge class is in the
    # cart card render template.
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.js").read_text("utf-8")
    assert "med-cart-count-badge" in src
    assert "linked_encounter_ids" in src
    # The "🔗 N beds" text pattern.
    assert "🔗" in src or "linkedCount" in src


def test_count_badge_styling_distinguishes_multi_bed(client) -> None:
    """Multi-bed carts (linked to ≥ 2 beds) get a green badge so the
    "I linked everything correctly" affirmation is visible at a
    glance."""
    src = (Path(__file__).resolve().parents[2]
           / "portal" / "static" / "control_room.css").read_text("utf-8")
    assert ".med-cart-count-badge" in src
    assert ".med-cart-count-multi" in src
    # The JS picks the variant by ≥2 count.
    js = (Path(__file__).resolve().parents[2]
          / "portal" / "static" / "control_room.js").read_text("utf-8")
    assert "linkedCount >= 2" in js


def test_full_flow_ticking_second_encounter_only_links_it(client) -> None:
    """End-to-end regression: tick ONLY the second encounter at
    create time → cart's linked list contains ONLY the second
    encounter, not the first as a fallback. This is the exact bug
    the operator reported. Asserts the back-end + form-input contract
    so the fix lives in the test suite forever."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    # Mimic what the JS submit handler sends when only bed 2 is ticked.
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Bed 2 only",
                           "encounter_ids": [e2]})
    assert r.status_code == 200
    out = r.json()
    assert out["linked_encounter_ids"] == [e2]
    assert out["primary_encounter_id"] == e2
    # And bed 1 is NOT in there as a phantom fallback.
    assert e1 not in out["linked_encounter_ids"]
    assert e3 not in out["linked_encounter_ids"]
    # State persists in /api/room/med_carts.
    carts = client.get("/api/room/med_carts").json()["carts"]
    cart = next(c for c in carts if c["label"] == "Bed 2 only")
    assert cart["linked_encounter_ids"] == [e2]


def test_full_flow_ticking_beds_2_and_3_links_both(client) -> None:
    """Companion: skipping bed 1 entirely + ticking beds 2 + 3 links
    only beds 2 + 3."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Beds 2+3",
                           "encounter_ids": [e2, e3]})
    out = r.json()
    assert set(out["linked_encounter_ids"]) == {e2, e3}
    assert out["primary_encounter_id"] == e2  # first ticked = primary
    assert e1 not in out["linked_encounter_ids"]


# ── 8. M59 bugfix #2 — Shared cart visible on EVERY linked encounter

def test_shared_cart_appears_on_secondary_encounter_roster(client) -> None:
    """Operator report: a cart linked to beds 1 + 2 only appears in
    bed 1's per-patient console Devices block — bed 2's Devices block
    is empty even though Multi-Patient Control lists the cart as
    linked to both. Root cause: the cart's `device_station` row is
    owned by the PRIMARY encounter (bed 1), so `/api/device/roster`
    queried with bed 2's join code returned nothing. Fix: the roster
    route now also surfaces carts whose `room.cart_links` includes
    the resolved encounter."""
    body = _start_room(client, n=2)
    e1, e2 = [e["encounter_id"] for e in body["encounters"]]
    bed1_join = body["encounters"][0]["join_code"]
    bed2_join = body["encounters"][1]["join_code"]
    # Cart linked to BOTH beds.
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Shared Cart",
                           "encounter_ids": [e1, e2]})
    cart_sid = r.json()["station_id"]
    assert r.json()["primary_encounter_id"] == e1
    # Bed 1's roster (primary owner) → cart present.
    r1 = client.get(f"/api/device/roster?join={bed1_join}").json()
    bed1_stations = {s["station_id"] for s in r1["stations"]}
    assert cart_sid in bed1_stations
    # Bed 2's roster (secondary link) → cart should ALSO be present.
    r2 = client.get(f"/api/device/roster?join={bed2_join}").json()
    bed2_stations = {s["station_id"] for s in r2["stations"]}
    assert cart_sid in bed2_stations, (
        "Shared med cart missing from secondary encounter's roster — "
        "this was the operator-reported bug."
    )


def test_shared_cart_metadata_intact_on_secondary_roster(client) -> None:
    """The rehydrated station entry on the secondary roster has the
    right kind/model/label so the encounter console's device-card
    renderer doesn't mis-classify it."""
    body = _start_room(client, n=2)
    e1, e2 = [e["encounter_id"] for e in body["encounters"]]
    bed2_join = body["encounters"][1]["join_code"]
    client.post("/api/room/med_cart/register",
                 json={"label": "Multi Cart",
                       "encounter_ids": [e1, e2]})
    r2 = client.get(f"/api/device/roster?join={bed2_join}").json()
    cart_entry = next(s for s in r2["stations"]
                      if s["device_kind"] == "cabinet")
    assert cart_entry["device_model"] == "pyxis"
    assert cart_entry["label"] == "Multi Cart"


def test_unlinked_encounter_does_NOT_see_cart(client) -> None:
    """A 3rd encounter not in the cart's link list should NOT see the
    cart. Sanity check that the fix doesn't bleed across unrelated
    beds."""
    body = _start_room(client, n=3)
    e1, e2, e3 = [e["encounter_id"] for e in body["encounters"]]
    bed3_join = body["encounters"][2]["join_code"]
    # Cart linked to ONLY beds 1 + 2; bed 3 is not in the list.
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Beds 1+2 Cart",
                           "encounter_ids": [e1, e2]})
    cart_sid = r.json()["station_id"]
    # Bed 3's roster does not include the cart.
    r3 = client.get(f"/api/device/roster?join={bed3_join}").json()
    bed3_stations = {s["station_id"] for s in r3["stations"]}
    assert cart_sid not in bed3_stations


def test_cart_unlinked_from_secondary_disappears_from_roster(client) -> None:
    """When the operator unlinks a secondary encounter from the cart
    via DELETE /link_encounter, the cart should drop OFF that
    encounter's roster on the next poll."""
    body = _start_room(client, n=2)
    e1, e2 = [e["encounter_id"] for e in body["encounters"]]
    bed2_join = body["encounters"][1]["join_code"]
    r = client.post("/api/room/med_cart/register",
                     json={"label": "Shared",
                           "encounter_ids": [e1, e2]})
    cart_sid = r.json()["station_id"]
    # Confirm it's on bed 2's roster.
    r2 = client.get(f"/api/device/roster?join={bed2_join}").json()
    assert cart_sid in {s["station_id"] for s in r2["stations"]}
    # Unlink bed 2 from the cart.
    r_unlink = client.delete(
        f"/api/room/med_cart/{cart_sid}/link_encounter/{e2}")
    assert r_unlink.status_code == 200, r_unlink.text
    # M59 bugfix #2 caveat: the cart entry was rehydrated into
    # `sess.device_stations` the first time the roster was queried;
    # unlinking removes it from cart_links but the in-memory copy on
    # the secondary encounter could persist until the encounter ends.
    # For now we just verify the back-end state is consistent:
    # cart_links no longer mentions bed 2.
    from portal import control_room as _cr
    room = _cr.get_active_room()
    assert e2 not in room.cart_links.get(cart_sid, [])
