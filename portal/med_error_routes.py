"""FR-008 S5 — control-room API for staged medication errors (instructor, auth'd).

GET  /api/control/mederrors            taxonomy + armed-error state (drives wizard + live card)
GET  /api/control/mederrors/suggest    ?type=&vector=&encounter= → grounded candidates
POST /api/control/mederrors/impacts    {type, payload} → curated impact menu for that candidate
POST /api/control/mederrors/arm        {type, vector, encounter, payload, impact?, note?}
POST /api/control/mederrors/disarm     {error_id}            (restores any chart edit)
POST /api/control/mederrors/trigger    {error_id, confirm_severe?}
POST /api/control/mederrors/stabilize  {error_id}
POST /api/control/mederrors/resolve    {error_id, outcome: caught|missed, note?}

Every lifecycle action stamps the operator transcript (debrief timeline). All state is
per-active-control-session, exactly like the med board."""
from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from portal import auth, control_session, credentials, med_errors


def _active_or_409() -> tuple[Any | None, JSONResponse | None]:
    sess = control_session.get_active()
    if sess is None:
        return None, JSONResponse(
            {"ok": False, "error": "no running scenario"}, status_code=409)
    return sess, None


def _stamp(sess: Any, line: str) -> None:
    """One operator-visible transcript entry (single, character-direction) —
    the debrief's staged-error timeline. Best-effort, never fails the action."""
    try:
        sess.transcript.append(control_session.TranscriptEntry(
            ts=time.time(), source="instructor", source_label="⚠️ Staged error",
            persona_id="", persona_name="Staged error",
            direction="character", text=line,
        ))
    except Exception:  # noqa: BLE001
        pass


def _err_line(rec: dict[str, Any]) -> str:
    return (f"{med_errors.TYPE_DISPLAY.get(rec['type'], rec['type'])} · "
            f"{rec['payload'].get('display', '')} · "
            f"{med_errors.ENCOUNTER_DISPLAY_SHORT.get(rec['encounter'], rec['encounter'])}")


def attach(app: Any) -> None:
    @app.get("/api/control/mederrors")
    async def api_mederrors(  # noqa: ANN202
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        return JSONResponse({"ok": True, "taxonomy": med_errors.taxonomy(),
                             **med_errors.state(sess.id)})

    @app.get("/api/control/mederrors/suggest")
    async def api_mederrors_suggest(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        q = request.query_params
        try:
            out = med_errors.suggest(sess.id, str(q.get("type") or ""),
                                     str(q.get("vector") or ""),
                                     str(q.get("encounter") or ""))
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return JSONResponse({"ok": True, "candidates": out})

    @app.post("/api/control/mederrors/impacts")
    async def api_mederrors_impacts(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        menu = med_errors.impact_menu(str(body.get("type") or ""),
                                      dict(body.get("payload") or {}))
        return JSONResponse({"ok": True, "profiles": menu})

    @app.post("/api/control/mederrors/arm")
    async def api_mederrors_arm(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        try:
            rec = med_errors.arm(
                sess.id,
                err_type=str(body.get("type") or ""),
                vector=str(body.get("vector") or ""),
                encounter=str(body.get("encounter") or ""),
                payload=dict(body.get("payload") or {}),
                impact=body.get("impact"),
                note=str(body.get("note") or ""),
            )
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        imp = rec.get("impact") or {}
        _stamp(sess, f"ARMED {rec['id']}: {_err_line(rec)}"
               + (f" · impact {imp.get('profile')}/{imp.get('severity')}"
                  f" ({imp.get('trigger')})" if imp else ""))
        return JSONResponse({"ok": True, "error_rec": rec})

    @app.post("/api/control/mederrors/disarm")
    async def api_mederrors_disarm(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        eid = str(body.get("error_id") or "")
        rec = med_errors.get(sess.id, eid)
        if not med_errors.disarm(sess.id, eid):
            return JSONResponse({"ok": False, "error": f"no staged error {eid}"},
                                status_code=404)
        _stamp(sess, f"DISARMED {eid}: {_err_line(rec)} (chart restored)")
        return JSONResponse({"ok": True})

    @app.post("/api/control/mederrors/trigger")
    async def api_mederrors_trigger(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        try:
            rec = med_errors.trigger_impact(
                sess.id, str(body.get("error_id") or ""),
                confirm_severe=bool(body.get("confirm_severe")))
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        st = rec.get("impact_state") or {}
        _stamp(sess, f"IMPACT TRIGGERED {rec['id']}: {st.get('profile')}/"
                     f"{st.get('severity')} — staged vitals applied")
        return JSONResponse({"ok": True, "error_rec": rec})

    @app.post("/api/control/mederrors/stabilize")
    async def api_mederrors_stabilize(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        try:
            rec = med_errors.stabilize(sess.id, str(body.get("error_id") or ""))
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        _stamp(sess, f"STABILIZED {rec['id']}: vitals walked back to baseline")
        return JSONResponse({"ok": True, "error_rec": rec})

    @app.post("/api/control/mederrors/resolve")
    async def api_mederrors_resolve(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        sess, err = _active_or_409()
        if err:
            return err
        body = await request.json()
        eid = str(body.get("error_id") or "")
        try:
            ok = med_errors.resolve(sess.id, eid,
                                    str(body.get("outcome") or ""),
                                    note=str(body.get("note") or ""))
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        if not ok:
            return JSONResponse({"ok": False, "error": f"no staged error {eid}"},
                                status_code=404)
        rec = med_errors.get(sess.id, eid)
        _stamp(sess, f"RESOLVED {eid} — {str(body.get('outcome') or '').upper()}: "
                     f"{_err_line(rec)}")
        return JSONResponse({"ok": True, "error_rec": rec})
