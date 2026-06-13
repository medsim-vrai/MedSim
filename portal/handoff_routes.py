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

    # ── H5/H6 — evaluation (score the handoff, view it, confirm coverage lines) ──
    @app.post("/api/control/handoff/evaluate")
    async def api_handoff_evaluate(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        """Score the handoff against the pack (per patient) from the live
        transcript + survey answers."""
        sess, err = _resolve(request)
        if err:
            return err
        from portal import handoff_eval
        h = handoff.get(sess.id)
        if not h:
            return JSONResponse({"ok": False, "error": "no handoff in progress"},
                                status_code=409)
        body = await request.json() if request.headers.get("content-type", "").startswith(
            "application/json") else {}
        only = str((body or {}).get("persona_id") or "")
        pids = [only] if only else list(h.get("persona_ids", []))
        evals = {pid: handoff_eval.build_evaluation(sess.id, pid) for pid in pids}
        return JSONResponse({"ok": True, "evaluations": evals, **handoff.state(sess.id)})

    @app.get("/api/control/handoff/evaluation")
    async def api_handoff_evaluation(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _resolve(request)
        if err:
            return err
        from portal import handoff_eval
        h = handoff.get(sess.id)
        evals = {pid: handoff_eval.get_evaluation(sess.id, pid)
                 for pid in (h.get("persona_ids", []) if h else [])}
        return JSONResponse({"ok": True,
                             "evaluations": {k: v for k, v in evals.items() if v}})

    @app.post("/api/control/handoff/confirm")
    async def api_handoff_confirm(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        """Instructor gate: confirm a coverage line (optionally override its
        said verdict) before it renders to the student."""
        sess, err = _resolve(request)
        if err:
            return err
        from portal import handoff_eval
        body = await request.json()
        said = body.get("said")
        ok = handoff_eval.confirm_coverage(
            sess.id, str(body.get("persona_id") or ""), str(body.get("element_id") or ""),
            said=said if isinstance(said, bool) else None,
            confirmed=bool(body.get("confirmed", True)))
        if not ok:
            return JSONResponse({"ok": False, "error": "no such coverage line"},
                                status_code=404)
        return JSONResponse({"ok": True,
                             "evaluation": handoff_eval.get_evaluation(
                                 sess.id, str(body.get("persona_id") or ""))})

    # ── H4 device-facing survey (on the STUDENT's station, same trust posture as
    #    /listen: no auth by default, ADR-0027 device token when enforced) ──────
    def _device_session(request: Request):
        """Resolve the active control session + optional token check for a
        device survey call. Returns (sess, error_response)."""
        from portal import control_session, vrai_faces
        sess = control_session.get_active()
        if sess is None:
            return None, JSONResponse({"ok": False, "error": "no running scenario"},
                                      status_code=409)
        if vrai_faces.token_enabled():
            scenario = str(request.query_params.get("scenario") or "default")
            character = str(request.query_params.get("character")
                            or request.query_params.get("cid") or "")
            token = str(request.query_params.get("token") or "")
            import hmac
            if not hmac.compare_digest(token, vrai_faces.face_token(scenario, character)):
                return None, JSONResponse({"ok": False, "error": "invalid device token"},
                                          status_code=403)
        return sess, None

    @app.get("/api/face/{character_id}/survey")
    async def api_face_survey(request: Request, character_id: str):  # noqa: ANN202
        """The post-handoff survey questions for the active handoff (mode-filtered).
        409 when no handoff is running."""
        sess, err = _device_session(request)
        if err:
            return err
        qs = handoff.survey_questions(sess.id)
        if not qs:
            return JSONResponse({"ok": False, "error": "no handoff in progress"},
                                status_code=409)
        h = handoff.get(sess.id) or {}
        return JSONResponse({"ok": True, "mode": h.get("mode"), "questions": qs})

    @app.post("/api/face/{character_id}/survey/answer")
    async def api_face_survey_answer(request: Request, character_id: str):  # noqa: ANN202
        """Store one voice answer {q, text} from the station."""
        sess, err = _device_session(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        q = str((body or {}).get("q") or "")
        text = str((body or {}).get("text") or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text required"}, status_code=400)
        try:
            ok = handoff.record_survey_answer(sess.id, q, text)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        if not ok:
            return JSONResponse({"ok": False, "error": "no handoff in progress"},
                                status_code=409)
        return JSONResponse({"ok": True})
