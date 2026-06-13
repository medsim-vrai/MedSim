"""FR-001/FR-002 — control-room API for the medication board (instructor-facing, auth'd).

GET  /api/control/meds              the session's med board (auto-inits: condition detected
                                    from the active scenario via ehr_seed.detect_condition,
                                    instructor can switch it)
POST /api/control/meds/condition    {condition} — switch condition (re-inits the board)
POST /api/control/meds/update       {id, in_cart?, in_pharmacy?, available?} — flip flags
POST /api/control/meds/add          {drug, dose, route, frequency, tier?, in_cart?,
                                     in_pharmacy?, available?} — instructor-added med (level 2)

All state is per-active-control-session (in-memory, like the session itself). The simulated
doctor/pharmacist read this board at turn time (med_orders.prompt_block_for)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from portal import auth, control_session, credentials, library, med_orders


def _active_or_409() -> tuple[Any | None, JSONResponse | None]:
    sess = control_session.get_active()
    if sess is None:
        return None, JSONResponse(
            {"ok": False, "error": "no running scenario"}, status_code=409)
    return sess, None


def _detect_default_condition(sess: Any) -> str:
    """Best-effort condition from the running scenario (ehr_seed's detector)."""
    try:
        from portal import ehr_seed
        # Role-aware: the med board's condition must come from the PATIENT, not
        # whoever is first in selected_personas (could be the doctor).
        pid = ehr_seed.patient_persona_id(sess) or ""
        persona = library.get_persona(pid) or {}
        modules = [m for m in (library.get_module(mid)
                               for mid in getattr(sess, "selected_modules", []) or []) if m]
        cond = ehr_seed.detect_condition(persona, modules,
                                         getattr(sess, "scenario_text", "") or "")
    except Exception:  # noqa: BLE001 — detection is convenience, never fatal
        cond = "stable_baseline"
    return cond if cond in {c["id"] for c in med_orders.conditions()} else "stable_baseline"


def _board_payload(sess: Any) -> dict[str, Any]:
    state = med_orders.get_state(sess.id)
    if state is None:
        state = med_orders.init_session(sess.id, _detect_default_condition(sess))
    return {"ok": True, "conditions": med_orders.conditions(), **state}


def attach(app: Any) -> None:
    @app.get("/api/control/meds")
    async def api_meds_board(  # noqa: ANN202
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        return JSONResponse(_board_payload(sess))

    @app.post("/api/control/meds/condition")
    async def api_meds_condition(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        cond = str((body or {}).get("condition") or "")
        if cond not in {c["id"] for c in med_orders.conditions()}:
            return JSONResponse({"ok": False, "error": "unknown condition"},
                                status_code=400)
        med_orders.init_session(sess.id, cond)
        return JSONResponse(_board_payload(sess))

    @app.post("/api/control/meds/update")
    async def api_meds_update(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json() or {}
        ok = med_orders.update_item(
            sess.id, str(body.get("id") or ""),
            in_cart=body.get("in_cart"),
            in_pharmacy=body.get("in_pharmacy"),
            available=body.get("available"),
        )
        if not ok:
            return JSONResponse({"ok": False, "error": "unknown item"}, status_code=404)
        return JSONResponse(_board_payload(sess))

    @app.post("/api/control/meds/add")
    async def api_meds_add(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        if med_orders.get_state(sess.id) is None:
            med_orders.init_session(sess.id, _detect_default_condition(sess))
        body = await request.json() or {}
        item = med_orders.add_custom(
            sess.id,
            drug=str(body.get("drug") or ""),
            dose=str(body.get("dose") or ""),
            route=str(body.get("route") or ""),
            frequency=str(body.get("frequency") or ""),
            tier=str(body.get("tier") or "alternative"),
            in_cart=bool(body.get("in_cart")),
            in_pharmacy=bool(body.get("in_pharmacy", True)),
            available=bool(body.get("available", True)),
        )
        if item is None:
            return JSONResponse({"ok": False, "error": "drug name required"},
                                status_code=400)
        return JSONResponse(_board_payload(sess))
