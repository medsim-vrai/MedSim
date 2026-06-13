"""FR-009 H2 — control-room API for the shift-handoff phase (instructor, auth'd).

GET  /api/control/handoff            current handoff state (+ ?bed= for a room)
POST /api/control/handoff/start      {mode, dial?, persona_ids?, counterpart_id}
POST /api/control/handoff/end        end the handoff phase

Per-active-session, exactly like the med board / staged errors. The chosen
counterpart character receives the handoff prompt block at turn time
(handoff.prompt_block_for); everyone else is unaffected. The control-room UI
that drives these lands in H6; the survey + scoring in H4/H5."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from portal import auth, control_session, credentials, ehr_seed, handoff


def _resolve(request: Request) -> tuple[Any | None, JSONResponse | None]:
    """Single-patient → the active session; multi-patient → ?bed=<encounter_id>
    (get_active is None in a multi-bed room). Mirrors med_error_routes."""
    bed = (request.query_params.get("bed") or "").strip()
    if bed:
        from portal import control_room
        room = control_room.get_active_room()
        sess = room.encounters.get(bed) if room else None
        if sess is None:
            return None, JSONResponse(
                {"ok": False, "error": f"bed {bed!r} is not in the active room"},
                status_code=404)
        return sess, None
    sess = control_session.get_active()
    if sess is None:
        return None, JSONResponse(
            {"ok": False, "error": "no running scenario"}, status_code=409)
    return sess, None


def attach(app: Any) -> None:
    @app.get("/api/control/handoff")
    async def api_handoff_state(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _resolve(request)
        if err:
            return err
        return JSONResponse({"ok": True, **handoff.state(sess.id)})

    @app.post("/api/control/handoff/start")
    async def api_handoff_start(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _resolve(request)
        if err:
            return err
        body = await request.json()
        persona_ids = body.get("persona_ids") or []
        if not persona_ids:                      # default to this session's patient
            pid = ehr_seed.patient_persona_id(sess)
            persona_ids = [pid] if pid else []
        # H3 — multi-patient: {persona_id: source_session_id} (which bed's chart
        # builds each patient's pack). Optional; single-patient ignores it.
        sources = body.get("patient_sources") or None
        try:
            handoff.start_handoff(
                sess.id,
                mode=str(body.get("mode") or ""),
                dial=str(body.get("dial") or "complete"),
                persona_ids=list(persona_ids),
                counterpart_id=str(body.get("counterpart_id") or ""),
                patient_sources=sources if isinstance(sources, dict) else None,
            )
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return JSONResponse({"ok": True, **handoff.state(sess.id)})

    @app.post("/api/control/handoff/advance")
    async def api_handoff_advance(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        """H3 — close the current patient and move to the next (or, after the
        last, to the cross-patient prioritization question)."""
        sess, err = _resolve(request)
        if err:
            return err
        nxt = handoff.advance_patient(sess.id)
        return JSONResponse({"ok": True, "next_patient": nxt, **handoff.state(sess.id)})

    @app.post("/api/control/handoff/end")
    async def api_handoff_end(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _resolve(request)
        if err:
            return err
        ended = handoff.end_handoff(sess.id)
        return JSONResponse({"ok": True, "ended": ended})
