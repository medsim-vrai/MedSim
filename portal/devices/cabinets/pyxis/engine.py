"""CabinetEngine — dispensing-cabinet state machine.

Used by BD Pyxis in v6.0; later versions reuse the same engine for
Omnicell XT, ARxIUM, Capsa, TouchPoint by varying ``spec.json``.

The workflow is patient-first: login → select patient → select verb →
select med → execute (with optional barcode scan and witness co-sign).
Controlled substances always require a witness; the engine tracks
witness state per transaction.

Event types:

  auth.login              {user, method}
  auth.logout             {}
  auth.witness            {witness_user}
  cabinet.select_patient  {patient_id, patient_name, mrn}
  cabinet.select_verb     {verb}                          # remove|return|waste|count|discrepancies|override
  cabinet.select_med      {med_id}
  cabinet.scan_verify     {scanned_ndc, expected_ndc, result}    # match|mismatch
  cabinet.remove          {patient_id, med_id, qty, witness_user?}
  cabinet.return          {patient_id, med_id, qty, witness_user?}
  cabinet.waste           {patient_id, med_id, amount, witness_user, reason}
  cabinet.count           {location, expected, actual}
  cabinet.override        {patient_id, med_id, qty, reason}
  cabinet.discrepancy_resolve {item_id, expected, actual, resolution, witness_user?}
  cabinet.restock         {med_id, qty}
  drawer.open             {drawer}
  drawer.close            {drawer}
  alarm.* (inherited)
"""
from __future__ import annotations

from typing import Any

from portal.devices.engine.state_machine import DeviceEngine


class CabinetEngine(DeviceEngine):
    device_kind = "cabinet"

    def initial_state(self) -> dict[str, Any]:
        meds = {m["id"]: dict(m) for m in self.spec["medications"]}
        return {
            "screen":              "lock",
            "session_user":        None,
            "witness_user":        None,
            "patient":             None,        # {id, name, mrn}
            "selected_verb":       None,
            "selected_med":        None,        # med_id
            "scan":                {"expected": None, "scanned": None, "result": "pending"},
            "witness_pending":     False,
            "drawers":             {},          # drawer_id → 'open'|'closed'|'lit'
            "active_alarms":       [],
            "active_alerts":       [],
            "discrepancies":       [],
            "medications":         meds,        # current inventory snapshot
            "transactions":        [],          # rolling tail of last 20
            # V6.1.6 — quick-checkoff log: one entry per "✓ Take" tap.
            "administrations":     [],
        }

    def apply(self, state: dict[str, Any],
              event: dict[str, Any]) -> dict[str, Any]:
        state = super().apply(state, event)
        et = event["type"]
        payload = event.get("payload", {}) or {}
        if et == "auth.login":
            return {**state, "session_user": payload.get("user"),
                    "screen": "menu", "active_alerts":
                    self._with_alert(state["active_alerts"], "login_success")}
        if et == "auth.logout":
            return {**state, "session_user": None, "witness_user": None,
                    "patient": None, "selected_verb": None,
                    "selected_med": None, "screen": "lock"}
        if et == "auth.witness":
            return {**state, "witness_user": payload.get("witness_user"),
                    "witness_pending": False}
        if et == "cabinet.select_patient":
            return {**state, "patient": {
                "id":   payload.get("patient_id"),
                "name": payload.get("patient_name"),
                "mrn":  payload.get("mrn"),
            }, "screen": "verbs"}
        if et == "cabinet.select_verb":
            return {**state, "selected_verb": payload.get("verb"),
                    "screen": "meds"}
        if et == "cabinet.select_med":
            med_id = payload.get("med_id")
            med = state["medications"].get(med_id)
            new_screen = "remove" if state["selected_verb"] in (None, "remove") else state["selected_verb"]
            return {**state, "selected_med": med_id, "screen": new_screen,
                    "scan": {"expected": med["ndc"] if med else None,
                              "scanned": None, "result": "pending"}}
        if et == "cabinet.scan_verify":
            res = payload.get("result", "pending")
            tone = "scan_success" if res == "match" else "scan_mismatch"
            return {**state,
                    "scan": {"expected": payload.get("expected_ndc"),
                              "scanned": payload.get("scanned_ndc"),
                              "result":  res},
                    "active_alerts": self._with_alert(state["active_alerts"], tone)}
        if et in ("cabinet.remove", "cabinet.return", "cabinet.waste",
                   "cabinet.override", "cabinet.restock"):
            med_id = payload.get("med_id")
            qty = float(payload.get("qty", 0) or 0)
            meds = dict(state["medications"])
            med = dict(meds.get(med_id, {}))
            if med:
                if et == "cabinet.remove" or et == "cabinet.waste" or et == "cabinet.override":
                    med["count"] = max(0, med.get("count", 0) - max(1, int(qty)))
                elif et == "cabinet.return" or et == "cabinet.restock":
                    med["count"] = med.get("count", 0) + max(1, int(qty))
                meds[med_id] = med
            # If the med needs witness and we don't have one yet, mark pending.
            needs_w = bool(med.get("requires_witness")) and not payload.get("witness_user")
            transactions = (state["transactions"] + [{
                "type": et, "ts": event["ts"], "med_id": med_id, "qty": qty,
                "patient": state.get("patient"),
                "witness_user": payload.get("witness_user"),
                "reason": payload.get("reason"),
            }])[-20:]
            alerts = state["active_alerts"]
            if et != "cabinet.restock":
                alerts = self._with_alert(alerts, "transaction_complete")
            # Inventory threshold alerts
            par = med.get("par_level", 0)
            cnt = med.get("count", 0)
            ratio = (cnt / par) if par else 1
            low_thr  = self.spec.get("low_inventory_threshold", 0.3)
            crit_thr = self.spec.get("critical_inventory_threshold", 0.15)
            if par and ratio <= crit_thr:
                alerts = self._with_alert(alerts, "inventory_low")
            elif par and ratio <= low_thr:
                alerts = self._with_alert(alerts, "inventory_low")
            return {**state, "medications": meds, "transactions": transactions,
                    "active_alerts": alerts,
                    "witness_pending": needs_w and et != "cabinet.restock",
                    "selected_med": None, "selected_verb": None,
                    "screen": "menu" if not needs_w else "witness"}
        if et == "cabinet.administer":
            # V6.1.6 — quick-checkoff path. No scan, no witness gate, no
            # drawer selection — the student taps "✓ Take" next to the
            # med row on the patient's mini-MAR and the event is logged
            # with character_id + med_name + scheduled_time + ts. The
            # engine state tracks a per-(character, med, scheduled_time)
            # set so the UI can show ✓ + admin time on subsequent loads.
            admins = list(state.get("administrations") or [])
            admins.append({
                "ts":              event["ts"],
                # med cart v2 actions: remove|return|waste|count|discrepancy|
                # override (+ legacy 'administer' = the give action)
                "action":          (payload.get("action") or "administer"),
                "character_id":    payload.get("character_id"),
                "character_name":  payload.get("character_name"),
                "med_name":        payload.get("med_name"),
                "med_location":    payload.get("med_location"),
                "scheduled_time":  payload.get("scheduled_time"),
                "dose":            payload.get("dose"),
                "route":           payload.get("route"),
                # med cart v2 — attribution: who pulled it (signed-in staff)
                "administered_by": payload.get("administered_by") or
                                    state.get("session_user") or "student",
                "administered_initials": payload.get("administered_initials") or "",
                "administered_role":     payload.get("administered_role") or "",
                "staff_id":              payload.get("staff_id") or "",
                "scan_used":       bool(payload.get("scan_used")),
            })
            return {**state, "administrations": admins[-200:]}
        if et == "cabinet.count":
            return state   # count itself doesn't mutate; resolve does
        if et == "cabinet.discrepancy_resolve":
            disc = list(state["discrepancies"])
            disc = [d for d in disc if d.get("item_id") != payload.get("item_id")]
            alerts = state["active_alerts"]
            if not disc:
                alerts = [a for a in alerts if a != "discrepancy_alert"]
            return {**state, "discrepancies": disc, "active_alerts": alerts}
        if et == "drawer.open":
            d = dict(state["drawers"])
            d[payload.get("drawer")] = "open"
            return {**state, "drawers": d,
                    "active_alerts": self._with_alert(state["active_alerts"], "drawer_open")}
        if et == "drawer.close":
            d = dict(state["drawers"])
            d[payload.get("drawer")] = "closed"
            alerts = [a for a in state["active_alerts"] if a != "drawer_open"]
            return {**state, "drawers": d, "active_alerts": alerts}
        return state

    @staticmethod
    def _with_alert(active: list[str], tone: str) -> list[str]:
        if tone in active:
            return active
        return [*active, tone]
