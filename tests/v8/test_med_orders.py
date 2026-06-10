"""FR-001/FR-002 — the medication-orders engine (authored data → code-selected orders)."""
from __future__ import annotations

from portal import med_orders


def setup_function(_fn) -> None:
    med_orders._SESSION_MEDS.clear()  # isolated session state per test


def test_catalog_loads_and_has_core_conditions() -> None:
    ids = {c["id"] for c in med_orders.conditions()}
    assert {"delirium", "alcohol_withdrawal", "sepsis", "anaphylaxis"} <= ids


def test_init_defaults_cart_empty_pharmacy_stocked() -> None:
    state = med_orders.init_session("s1", "delirium")
    assert state["items"], "delirium must have options"
    assert all(it["in_pharmacy"] and it["available"] and not it["in_cart"]
               for it in state["items"])
    tiers = {it["tier"] for it in state["items"]}
    assert tiers == {"primary", "alternative"}


def test_doctor_pick_is_seeded_and_deterministic_per_session() -> None:
    med_orders.init_session("s1", "delirium")
    a = med_orders.recommend_for_doctor("s1", [])
    b = med_orders.recommend_for_doctor("s1", [])
    assert a is not None and a["tier"] == "primary"
    assert a["id"] == b["id"], "same session → same pick (seeded)"


def test_doctor_excludes_already_on_and_escalates() -> None:
    state = med_orders.init_session("s1", "delirium")
    primaries = [it["drug"] for it in state["items"] if it["tier"] == "primary"]
    # already on one primary → the other primary is picked
    rec = med_orders.recommend_for_doctor("s1", [primaries[0]])
    assert rec is not None and rec["drug"] != primaries[0] and rec["tier"] == "primary"
    # already on ALL primaries → escalate to an alternative
    rec2 = med_orders.recommend_for_doctor("s1", primaries)
    assert rec2 is not None and rec2["tier"] == "alternative"
    # on everything → None (defer to instructor)
    all_drugs = [it["drug"] for it in state["items"]]
    assert med_orders.recommend_for_doctor("s1", all_drugs) is None


def test_doctor_ignores_availability_pharmacist_respects_it() -> None:
    state = med_orders.init_session("s1", "delirium")
    # flag every primary unavailable
    for it in state["items"]:
        if it["tier"] == "primary":
            med_orders.update_item("s1", it["id"], available=False)
    doc = med_orders.recommend_for_doctor("s1", [])
    assert doc is not None and doc["tier"] == "primary", \
        "the doctor orders by best practice regardless of supply (the teaching loop)"
    block = med_orders.pharmacist_prompt_block("s1")
    assert "NOT available" in block
    assert doc["drug"] in block  # the unavailable primary is named on the stock board


def test_add_custom_med_and_flags() -> None:
    med_orders.init_session("s1", "sepsis")
    item = med_orders.add_custom("s1", drug="Vancomycin", dose="15 mg/kg", route="IV",
                                 frequency="q12h", tier="alternative",
                                 in_cart=True, in_pharmacy=True, available=True)
    assert item is not None and item["custom"] and item["in_cart"]
    state = med_orders.get_state("s1")
    assert any(it["drug"] == "Vancomycin" for it in state["items"])


def test_role_detection() -> None:
    assert med_orders.role_kind("ED Attending") == "doctor"
    assert med_orders.role_kind("Hospitalist") == "doctor"
    assert med_orders.role_kind("Inpatient Pharmacist") == "pharmacist"
    assert med_orders.role_kind("Charge RN") is None
    assert med_orders.role_kind("Hyperactive Delirium") is None


def test_prompt_block_for_routes_by_role() -> None:
    med_orders.init_session("s1", "delirium")
    doc_block = med_orders.prompt_block_for("s1", {"role": "Hospitalist"})
    ph_block = med_orders.prompt_block_for("s1", {"role": "Inpatient Pharmacist"})
    none_block = med_orders.prompt_block_for("s1", {"role": "Adult Patient"})
    assert "MEDICATION ORDERS" in doc_block and "EXACTLY" in doc_block
    assert "PHARMACY STOCK BOARD" in ph_block
    assert none_block == ""
