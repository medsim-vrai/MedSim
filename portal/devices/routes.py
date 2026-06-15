"""HTTP routes for the v6 device subsystem.

Two surfaces, mirroring the EHR/control split that already exists in v5:

- **Public, join-code gated** — `/device/join`, `/device/{join}/{station}`,
  `/api/device/{station_id}/bootstrap|state|event|heartbeat`. A device
  station's join_code is its auth token, like the EHR /ehr/join flow.

- **Operator-only** — `/api/device/register`, `/api/device/{station_id}/
  inject`, `/api/device/{station_id}/assign`. Gated by ``auth.require_vault``
  the same way `/portal/control/*` is gated in v5.
"""
from __future__ import annotations

import os
import re
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from portal import auth, control_room, control_session, credentials, ehr_db, qrgen
from portal.devices import registry, ws as devices_ws
from portal.devices.engine import alarms as alarms_lib
from portal.devices.engine.state_machine import make_engine


router = APIRouter()
ws_router = APIRouter()
templates: Jinja2Templates | None = None     # set by attach()


# ──────────────────────────────────────────────────────────────────────
# M43 — Multi-patient session resolver.
#
# Every operator-facing device route used to call
# `control_session.get_active()` and 409 with "No active session"
# when it returned None.  In v7 multi-encounter rooms that's the
# default state — there's no singleton, just a room of encounters
# (each of which IS a ControlSession dataclass).  These helpers find
# the right session/encounter without breaking the v6 singleton path.
# ──────────────────────────────────────────────────────────────────────


def _session_for_station(station: dict) -> control_session.ControlSession | None:
    """Resolve the ControlSession that owns a given device station.

    Tries (in order):
      1. The v6 singleton via `control_session.get_active()`. Works in
         single-patient mode and any v6 fallback.
      2. The active multi-patient room's encounters dict, keyed by the
         station's stored `session_id` (which IS the encounter id in
         v7 per the M2 rename — `Encounter` is a `ControlSession`).
    Returns None when no match exists (caller raises 409).
    """
    sid = station.get("session_id") if station else None
    sess = control_session.get_active()
    if sess is not None and (sid is None or sess.id == sid):
        return sess
    if sid is None:
        return None
    room = control_room.get_active_room()
    if room is None:
        return None
    return room.encounters.get(sid)


def _session_for_join(join: str | None) -> control_session.ControlSession | None:
    """Resolve a session by an operator-supplied join code, falling
    back to v6 singleton.  Used by `/api/device/register` (which has
    no station_id yet to look up) and `/api/device/roster` (which
    can be scoped by an encounter's join code in multi-patient mode)."""
    if join:
        sess = control_session.get_by_join_code(join)
        if sess is not None:
            return sess
    return control_session.get_active()


def attach(app: Any, jinja: Jinja2Templates) -> None:
    """Wire the routers + templates onto the main FastAPI app."""
    global templates
    templates = jinja
    app.include_router(router)
    app.include_router(ws_router)


# ──────────────────────────────────────────────────────────────────────
# Public — device station HTML shell + join landing
# ──────────────────────────────────────────────────────────────────────

@router.get("/d")
async def device_qr_redirector(request: Request, c: str = "", s: str = ""):
    """Cross-platform QR redirector (rewritten 2026-06-10, was V6). The QR encodes this
    tiny /d URL (short → scannable); we redirect to the join page on the SAME ORIGIN AND
    SCHEME the request arrived on, in whatever browser the tablet's camera opened.

    The V6 version hard-coded `http://` targets and force-bounced iOS into Chrome via
    `googlechrome://` — both written in the portal's pre-TLS era. With the portal now
    HTTPS-only (ADR-0028), the http bounce hit the TLS port as plaintext and DIED on every
    platform (the field "security conflict", 2026-06-09), and the Chrome handoff errored on
    iPads without Chrome. The device skins are plain same-origin web pages (no Chrome-only
    APIs — audited 2026-06-10), so the platform default browser is correct everywhere:
    Safari on iPadOS, Chrome on Android. A relative server-side redirect preserves
    scheme/host/port by construction and needs no UA sniffing.

    Tablets must trust the MedSim dev root CA first (one-time) — see
    docs/CERTIFICATES-AND-NETWORK-CHANGES.md; without it the browser shows the
    untrusted-cert interstitial before this redirect can even run.
    """
    safe_c = re.sub(r"[^A-Za-z0-9_-]", "", (c or ""))[:32]
    safe_s = re.sub(r"[^A-Za-z0-9_-]", "", (s or ""))[:64]
    return RedirectResponse(
        url=f"/device/join?code={safe_c}&station={safe_s}", status_code=307)


@router.get("/device/join", response_class=HTMLResponse)
async def device_join(request: Request, code: str = "", station: str = ""):
    sess = control_session.get_by_join_code(code.strip()) if code else None
    station_info = ehr_db.get_device_station(station) if station else None
    err = None
    if code and sess is None:
        err = "Unknown join code."
    elif station and station_info is None:
        err = "Unknown device station."
    elif station_info and sess and station_info["session_id"] != sess.id:
        err = "Device belongs to a different session."
    if templates is None:
        return HTMLResponse(f"<pre>missing templates: {err or ''}</pre>")
    assignment = ehr_db.current_assignment(station) if station else None
    return templates.TemplateResponse(
        request, "device_join.html",
        {"code": code, "station": station_info, "error": err,
         "assignment": assignment, "session_id": sess.id if sess else None},
    )


@router.get("/device/{join_code}/{station_id}", response_class=HTMLResponse)
async def device_app(request: Request, join_code: str, station_id: str):
    sess = control_session.get_by_join_code(join_code)
    station = ehr_db.get_device_station(station_id)
    if sess is None or station is None or station["session_id"] != sess.id:
        raise HTTPException(404, "Session or station not found.")
    if templates is None:
        return HTMLResponse("<pre>missing templates</pre>")
    # M51 — The Patient Integrated Alarm renders a dedicated
    # control-surface UI (4 big buttons + flashing alarm canvas + M49
    # sound playback) rather than the vendor-skin overlay used for
    # pumps/cabinets.  Branch by kind here so the device-side bundle
    # stays simple per kind.
    template_name = "device_app.html"
    if station.get("device_kind") == "patient_integrated_alarm":
        template_name = "device_pia.html"
    return templates.TemplateResponse(
        request, template_name,
        {"join_code": join_code, "station": station,
         "device_kind": station["device_kind"],
         "device_model": station["device_model"]},
    )


# ──────────────────────────────────────────────────────────────────────
# Public — device-side API
# ──────────────────────────────────────────────────────────────────────

_ADVANCED_DEVICE_KINDS = ("telemetry_monitor", "vent_monitor", "ventilator")


def _physiology_view(device_kind: str, encounter_id: str, *,
                     evaluate: bool = False) -> dict[str, Any] | None:
    """FR-012 — the live physiology snapshot attached to an advanced device's
    bootstrap/state payload (None for basic pump/cabinet devices). When
    ``evaluate`` is set (telemetry monitor opening), re-run the auto-alarm
    evaluation first so the monitor reflects current breaches immediately."""
    if device_kind not in _ADVANCED_DEVICE_KINDS:
        return None
    try:
        from portal import physiology
        if evaluate and device_kind == "telemetry_monitor":
            from portal import telemetry_monitor
            telemetry_monitor.evaluate(encounter_id)
        return physiology.read(encounter_id)
    except Exception:  # noqa: BLE001 — physiology view is best-effort
        return None


def _vent_view(device_kind: str, encounter_id: str, *,
               evaluate: bool = False) -> dict[str, Any] | None:
    """FR-012 D4 — the ventilator numerics + settings/faults attached to a
    vent_monitor / ventilator payload (None otherwise). When ``evaluate`` is set
    (device opening), re-run the vent auto-alarm evaluation first."""
    if device_kind not in ("vent_monitor", "ventilator"):
        return None
    try:
        from portal import vent_state
        if evaluate:
            vent_state.evaluate(encounter_id)
        # The ventilator client needs the full control surface (ranges + modes +
        # set-vs-measured); the vent monitor only displays numerics + faults.
        if device_kind == "ventilator":
            return vent_state.controls_view(encounter_id)
        return vent_state.view(encounter_id)
    except Exception:  # noqa: BLE001 — vent view is best-effort
        return None


@router.get("/api/device/{station_id}/bootstrap")
async def api_device_bootstrap(station_id: str):
    """V6 — wrapped in try/except so the next 500 returns a JSON body
    with the exception class + message + stage. Without this the device
    front-end just sees 'bootstrap 500' and has nowhere to look."""
    import traceback as _tb, sys as _sys
    stage = "lookup"
    try:
        station = ehr_db.get_device_station(station_id)
        if station is None:
            raise HTTPException(404, "Station not found.")
        # M43/M47 — resolve the session via the station's stored
        # session_id (works in v7 multi-patient where get_active()
        # returns None). Falls through to v6 singleton for legacy.
        sess = _session_for_station(station)
        if sess is None:
            raise HTTPException(409, "No active session — operator probably ended or restarted the scenario.")
        stage = "load_spec"
        spec = registry.load_spec(station["device_kind"], station["device_model"])
        stage = "load_skin"
        skin = registry.load_skin(station["device_kind"], station["device_model"])
        stage = "current_assignment"
        assignment = ehr_db.current_assignment(station_id) or {}
        stage = "make_engine"
        engine = make_engine(session_id=sess.id, station_id=station_id,
                             device_kind=station["device_kind"],
                             device_model=station["device_model"])
        stage = "audio_catalog"
        audio = {
            tone: alarms_lib.audio_url(station["device_kind"], tone)
            for tone in alarms_lib.catalog_for(station["device_kind"])
        }
        stage = "engine.fold"
        state = engine.fold()
        # V6.1.6 / M47 — Per-patient MAR payload for the cart UI.
        #
        # Single-patient (v6) or unlinked cart: just the session's
        #   own selected personas + their MAR seed.
        # Room-level cart (M47) with `cart_links[station_id]`: merge
        #   MAR seeds across every linked encounter so the cabinet UI
        #   shows ONE list with sections per linked patient. Each
        #   character dict carries `encounter_id` so the dispense
        #   event handler can route the transcript entry to the
        #   right encounter (see /api/device/{sid}/event below).
        characters: list[dict[str, Any]] = []
        if station["device_kind"] == "cabinet":
            try:
                from portal import ehr_seed as _ehr_seed
                room = control_room.get_active_room()
                cart_links = (room.cart_links.get(station_id) or []) if room else []
                # Build the encounter set: linked encounters (M47) OR
                # just this station's own session (v6 single-patient
                # fallback).
                if cart_links and room is not None:
                    enc_list = [room.encounters[eid] for eid in cart_links
                                  if eid in room.encounters]
                else:
                    enc_list = [sess]
                # Pull each encounter's per-persona MAR seed, tagging
                # every character with its source encounter_id so the
                # dispense handler can route the transcript.
                #
                # M55 — if the instructor has marked an explicit
                # "active at start" subset on the encounter's
                # Medications card, filter THIS persona's medications
                # to that subset. No entry for a persona → show every
                # med (back-compat with pre-M55 behaviour).
                #
                # M58 — Operator: "Med list should only populate with
                # Patient character medications no other character."
                # The cart now only ever sees the patient persona
                # (family / clinician role-players have no MAR), so
                # `per_enc` is the patient-only seed, not the full
                # roster.
                for enc in enc_list:
                    per_enc = _ehr_seed.seeds_for_patient_only(
                        enc, ehr_id=enc.ehr_id) or []
                    active_map = getattr(enc, "active_medications",
                                          {}) or {}
                    for c in per_enc:
                        pid = c.get("character_id") or ""
                        if pid in active_map:
                            active_lower = {
                                n for n in (active_map.get(pid) or [])
                            }
                            c["medications"] = [
                                m for m in (c.get("medications") or [])
                                if (m.get("name") or "").strip().lower()
                                   in active_lower
                            ]
                        c["encounter_id"] = enc.id
                        c["encounter_label"] = (
                            enc.encounter_label or enc.scenario_name)
                        characters.append(c)
            except Exception:
                characters = []
        # FR-012 — advanced devices carry a live physiology snapshot so the
        # monitor/vent client renders real vitals; opening a telemetry monitor
        # re-evaluates its auto alarms so it reflects current breaches at once.
        physiology_view = _physiology_view(station["device_kind"], sess.id,
                                           evaluate=True)
        vent_view = _vent_view(station["device_kind"], sess.id, evaluate=True)
        return JSONResponse({
            "station":      station,
            "session_id":   sess.id,
            "session_state": sess.state,
            "spec":         spec,
            "skin_svg":     skin,
            "character_id": assignment.get("character_id"),
            "audio_urls":   audio,
            "state":        state,
            "characters":   characters,
            "physiology":   physiology_view,
            "vent":         vent_view,
        })
    except HTTPException:
        raise
    except Exception as exc:
        # Log full traceback to the server, surface a short JSON to the client.
        tb = _tb.format_exc()
        print(f"[MEDSIM] bootstrap 500 station={station_id} stage={stage}\n{tb}",
              file=_sys.stderr)
        return JSONResponse(
            {"detail": f"bootstrap failed in stage '{stage}': {type(exc).__name__}: {exc}",
             "stage": stage,
             "exception": type(exc).__name__},
            status_code=500,
        )


@router.get("/api/device/{station_id}/state")
async def api_device_state(station_id: str):
    """Poll fallback for the device state fold — used when WebSocket
    is temporarily down.

    M43-followup — pre-fix this route called `control_session.get_active()`
    which returns None in multi-patient mode, so every 2 s poll on
    every device tablet 409'd ("No active session"). The badge in
    the upper-right of the cart screen flashed OFFLINE · HTTP 409
    constantly even though WS was happily delivering folds. Fixed
    by using `_session_for_station(station)` like every other route
    that M43 touched (bootstrap / event / inject / clear / assign /
    roster all use that resolver).
    """
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409,
            "No active session linked to this device station.")
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    return JSONResponse({
        "session_state": sess.state,
        "state": engine.fold(),
        "physiology": _physiology_view(station["device_kind"], sess.id),
        "vent": _vent_view(station["device_kind"], sess.id),
    })


@router.post("/api/device/{station_id}/event")
async def api_device_event(station_id: str, request: Request):
    """HTTP fallback for posting a device-side event if WS is unavailable.

    M47 — When a `med.dispensed` event fires on a med cart linked to
    one or more encounters, write a transcript entry to whichever
    linked encounter owns the named patient. Payload conventions:
      - `character_id` (required) — persona id the med is being
        dispensed for; identifies which encounter's transcript to
        write.
      - `medication` (str), `amount` (str), `unit` (str) — what was
        dispensed.
      - `wasted` (str|None), `wasted_witness` (str|None) — when an
        excess amount is dropped, the volume + the witness's name.
      - `dispensed_by` (str|None) — student name (if known).
    Any subset is fine; the transcript line composes from what's
    present. Non-`med.dispensed` events are unaffected.
    """
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)   # M43 — multi-patient aware
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    if sess.state == "paused":
        return JSONResponse({"ok": False, "reason": "paused"}, status_code=423)
    body = await request.json()
    ev_type = (body.get("type") or "").strip()
    if not ev_type:
        raise HTTPException(400, "Missing 'type'.")
    payload = body.get("payload") or {}
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    state = engine.handle(type=ev_type, surface="device", payload=payload)
    # FR-008 S4: administering the staged med fires its configured patient
    # impact (per-error opt-in, severe pre-confirmed at arm). Best-effort —
    # must never break a device event.
    if ev_type in ("cabinet.administer", "med.administer"):
        try:
            from portal import med_errors as _me
            _me.note_med_administered(
                sess.id,
                str(payload.get("med_name") or payload.get("medication")
                    or payload.get("name") or ""))
        except Exception:  # noqa: BLE001
            pass
    ehr_db.touch_device_station(station_id)
    if station_id in sess.device_stations:
        sess.device_stations[station_id].touch()
    # M47 — Route med dispenses on cabinets to the right encounter's
    # transcript. We do this AFTER engine.handle so the event is
    # persisted to the device's event log first; transcript write
    # is non-fatal (logs the failure but returns ok=True).
    if ev_type == "med.dispensed" and station["device_kind"] == "cabinet":
        try:
            _log_cart_dispense_to_transcript(
                station_id=station_id, payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            import sys as _sys
            print(f"[MEDSIM] cart dispense transcript log failed: {exc}",
                  file=_sys.stderr)
    # M51 — Patient Integrated Alarm button press handling. The PIA
    # tablet posts `type="pia.button"` with payload `{action: ...}`.
    #   call_bell / bed_alarm → write an alarm.injected device_event
    #     so the alarm bus picks it up (M26 + M49 sound).
    #   code_blue → fire the actual code.blue scene at this encounter
    #     so the alarm cascades to nurse station + other PIA devices
    #     in the room (which poll /api/room/alarms and flash to show
    #     "code blue at Bed N").
    #   intercom_request → write a comm.intercom_request chart event;
    #     the nurse station's UI surfaces it as a request.
    if (ev_type == "pia.button" and
            station["device_kind"] == "patient_integrated_alarm"):
        try:
            _handle_pia_button(sess, station, station_id, payload)
        except Exception as exc:  # noqa: BLE001
            import sys as _sys
            print(f"[MEDSIM] PIA button handler failed: {exc}",
                  file=_sys.stderr)
    return JSONResponse({"ok": True, "state": state})


def _handle_pia_button(sess: control_session.ControlSession,
                        station: dict, station_id: str,
                        payload: dict) -> None:
    """M51 — Route a PIA button press to the right downstream effect."""
    action = (payload.get("action") or "").strip()
    if not action:
        return
    if action == "code_blue":
        # Fire the real code.blue scene at this encounter — same scene
        # the instructor's scene-inject would fire. This writes the
        # chart events + raises a code.blue alarm that propagates via
        # /api/room/alarms to every PIA + the nurse station + the
        # operator dashboard.
        from portal import scenes as _scenes
        _scenes.apply(sess, {"kind": "code.blue", "params": {}},
                      by=f"pia:{station_id}")
        return
    if action in ("call_bell", "bed_alarm"):
        # Write an alarm.injected device_event so the alarm bus
        # surfaces it. tone names align with the M49 sound library.
        ehr_db.append_device_event(
            sess.id, station_id,
            type="alarm.injected", surface="device",
            payload={"tone": action, "by": "patient"},
        )
        return
    if action == "intercom_request":
        # The bedside is asking the nurse station to start the
        # intercom. We write a comm.intercom_request chart event;
        # the nurse station can poll the chart for these or read
        # them off /api/encounter/{id}/transcript.
        ehr_db.append_event(
            sess.id, station_id,
            type="comm.intercom_request", surface="device",
            payload={"by": "patient",
                     "station_id": station_id,
                     "device_kind": "patient_integrated_alarm"},
        )
        # Also log a transcript entry so the supervisor sees it on
        # the encounter's transcript pane immediately.
        try:
            sess.log_turn(
                source=f"device:{station_id}",
                source_label="Patient Integrated Alarm",
                persona_id=sess.patient_persona_id or "",
                persona_name="Patient",
                student_text="🎙 Intercom requested",
                character_text="",
                latency_ms=None,
            )
        except Exception:  # noqa: BLE001
            pass
        return


def _log_cart_dispense_to_transcript(
    *, station_id: str, payload: dict[str, Any],
) -> None:
    """M47 — Write a transcript entry to the encounter that owns the
    persona named in a cart dispense payload.

    Resolution order for the target encounter:
      1. The cart's `cart_links` list (room-level cart) — find the
         entry whose `selected_personas` contains the payload's
         `character_id`.
      2. Fall back to the cart's primary session (v6 path / single-
         encounter cart).
    If neither matches, the transcript write is skipped.
    """
    from portal import control_room as _cr, library as _library
    room = _cr.get_active_room()
    if room is None:
        return
    character_id = (payload.get("character_id") or "").strip()
    if not character_id:
        return
    # Find the linked encounter that owns this persona.
    target_enc = None
    linked = room.cart_links.get(station_id) or []
    for eid in linked:
        enc = room.encounters.get(eid)
        if enc is None:
            continue
        if character_id == enc.patient_persona_id \
                or character_id in enc.selected_personas:
            target_enc = enc
            break
    if target_enc is None:
        # Fallback: cart's primary session.
        station = ehr_db.get_device_station(station_id) or {}
        sid = station.get("session_id")
        if sid and sid in room.encounters:
            target_enc = room.encounters[sid]
    if target_enc is None:
        return
    # Compose a human-readable line.
    cart_label = room.cart_labels.get(station_id) or "Med cart"
    med   = (payload.get("medication") or payload.get("med") or "").strip()
    amt   = (payload.get("amount") or "").strip()
    unit  = (payload.get("unit") or "").strip()
    waste = (payload.get("wasted") or "").strip()
    witness = (payload.get("wasted_witness")
               or payload.get("witness") or "").strip()
    by    = (payload.get("dispensed_by") or "").strip()
    parts: list[str] = [f"💊 {cart_label}"]
    parts.append(f"dispensed {med}" if med else "dispensed a medication")
    if amt:
        parts.append(f"{amt} {unit}".strip())
    if by:
        parts.append(f"by {by}")
    if waste:
        line = f"wasted {waste} {unit}".strip()
        if witness:
            line += f" (witness: {witness})"
        parts.append(line)
    line = " · ".join(parts)
    # Resolve persona display name for the transcript metadata.
    p = _library.get_persona(character_id) if character_id else None
    persona_name = (p.get("name") if p else character_id)
    target_enc.log_turn(
        source=f"device:{station_id}",
        source_label=cart_label,
        persona_id=character_id,
        persona_name=persona_name,
        student_text=line,
        character_text="",   # one-direction event line; no character reply
        latency_ms=None,
    )


@router.post("/api/device/{station_id}/heartbeat")
async def api_device_heartbeat(station_id: str):
    ehr_db.touch_device_station(station_id)
    sess = control_session.get_active()
    if sess and station_id in sess.device_stations:
        sess.device_stations[station_id].touch()
    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────
# Operator-only
# ──────────────────────────────────────────────────────────────────────

@router.post("/api/device/register")
async def api_device_register(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    join: str | None = None,
):
    """Create a new DeviceStation and return its bootstrap URL + a QR
    code so the instructor can hand the device a join code to scan.

    M43 — accepts `?join=<code>` so the route works in v7 multi-
    encounter rooms (where `control_session.get_active()` returns None).
    Falls back to the v6 singleton when no `join` is given.
    """
    sess = _session_for_join(join)
    if sess is None:
        raise HTTPException(
            409,
            "No active session. In multi-patient mode, open the device "
            "manager from a Per-Patient Console — it passes ?join=<code> "
            "automatically.",
        )
    body = await request.json()
    device_kind  = body.get("device_kind", "").strip()
    device_model = body.get("device_model", "").strip()
    label        = body.get("label", "").strip()
    if device_kind not in registry.KIND_DIRS:
        raise HTTPException(400, f"Unknown device_kind {device_kind!r}.")
    if device_model not in registry.available_models(device_kind):
        raise HTTPException(400, f"Unknown device_model {device_model!r}.")
    # M44 — Med carts are a room-level resource. Reject `cabinet`
    # creation from an encounter-scoped (?join=) call. The Multi-
    # Patient Control dashboard owns the "+ Add med cart" flow (M45).
    # We detect "encounter scope" by checking whether the resolved
    # session is one of the active room's encounters (vs. the v6
    # singleton, which is allowed to mint cabinets the legacy way).
    if device_kind == "cabinet" and join:
        room = control_room.get_active_room()
        if room is not None and sess.id in room.encounters:
            raise HTTPException(
                409,
                "Med carts (cabinets) are a room-level resource. "
                "Open the Multi-Patient Control page to add a cart, "
                "then link this encounter to it.",
            )
    station_id = "dev_" + secrets.token_hex(6)
    ehr_db.register_device_station(
        sess.id, station_id,
        device_kind=device_kind, device_model=device_model,
        label=label, user_agent=request.headers.get("user-agent", ""),
    )
    sess.add_device_station(station_id, device_kind=device_kind,
                            device_model=device_model, label=label,
                            user_agent=request.headers.get("user-agent", ""))
    # Encode a deep link the device's phone-camera scanner can open.
    # V6 — must NOT use request.base_url here: that returns whatever host
    # the operator hit (often 127.0.0.1 from the laptop), which is
    # meaningless to a phone on the same wifi. Use the LAN-routable URL
    # so the iPhone/iPad can actually reach the server. The v5 helper
    # _base_url_for_qr already implements this fallback (host header →
    # LAN IP if loopback).
    from portal.server import _base_url_for_qr, _lan_ip
    base = _base_url_for_qr(request).rstrip("/")
    join_url = f"{base}/device/join?code={sess.join_code}&station={station_id}"

    # V6 — open-in-Chrome strategy. The QR has to work on BOTH iOS and
    # Android, and the two platforms have different mechanisms:
    #   iOS:     supports googlechrome:// scheme but iOS Camera handles
    #            it cleanly because Safari is the default
    #   Android: supports googlechrome:// scheme too, but many camera apps
    #            (especially Samsung) refuse to treat non-http schemes
    #            as URLs and just show the raw text
    # So the default mode encodes a plain http:// URL pointing to a
    # tiny /d redirector page on this same server. Every QR scanner
    # handles plain http://, the page detects the platform with JS, and
    # bounces to Chrome via the right per-platform mechanism (or just
    # continues if already in Chrome). One QR works everywhere.
    #
    # MEDSIM_QR_OPEN_IN override:
    #   "smart"   (default) — /d landing page, works on both platforms
    #   "default"           — plain http:// (opens in system default browser)
    #   "ios"               — googlechrome:// scheme (iOS-only; old behavior)
    mode = (os.environ.get("MEDSIM_QR_OPEN_IN") or "smart").strip().lower()
    if mode == "default":
        qr_url = join_url
    elif mode == "ios":
        if join_url.startswith("https://"):
            qr_url = "googlechromes://" + join_url[len("https://"):]
        elif join_url.startswith("http://"):
            qr_url = "googlechrome://" + join_url[len("http://"):]
        else:
            qr_url = join_url
    else:   # "smart" (default)
        qr_url = f"{base}/d?c={sess.join_code}&s={station_id}"

    # Friendly diagnostic if the server is bound to loopback only —
    # _base_url_for_qr will print the LAN IP in the URL, but if the
    # server isn't actually LISTENING on that interface the phone gets
    # ERR_CONNECTION_REFUSED. The bind host comes from the same env var
    # run_portal.py reads.
    warning = None
    bind_host = os.environ.get("MEDSIM_HOST", "127.0.0.1").strip()
    if bind_host in ("127.0.0.1", "localhost", "::1"):
        warning = ("The server is bound to loopback only — devices on the "
                   "wifi will get ERR_CONNECTION_REFUSED. Stop the server "
                   "(Ctrl+C) and relaunch with: "
                   "MEDSIM_HOST=0.0.0.0 ./.venv/bin/python run_portal.py")

    return JSONResponse({
        "ok": True,
        "station_id": station_id,
        "join_url": join_url,
        "qr_url":   qr_url,
        "qr_svg":   qrgen.make_qr_svg(qr_url),
        "lan_ip":   _lan_ip(),
        "warning":  warning,
    })


@router.post("/api/device/{station_id}/inject")
async def api_device_inject(
    station_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)   # M43 — multi-patient aware
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    tone = (body.get("tone") or "").strip()
    if not tone:
        raise HTTPException(400, "Missing 'tone'.")
    # Validate the tone is in the device kind's catalogue.
    catalog = alarms_lib.catalog_for(station["device_kind"])
    if tone not in catalog:
        raise HTTPException(400, f"Unknown tone for {station['device_kind']}: {tone!r}")
    payload = {"tone": tone}
    if body.get("note"):
        payload["note"] = body["note"]
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    # FR-012 — a telemetry monitor's "alarm" is a CLINICAL CONDITION: drive the
    # physiology so HR/ECG/SpO2 actually change, then the monitor auto-fires the
    # matching alarm and the display reflects it. Equipment/advisory tones (leads
    # off, frequent PVCs) have no physiology mapping and fall through to a tone.
    if station["device_kind"] == "telemetry_monitor":
        from portal import telemetry_monitor
        if telemetry_monitor.inject_clinical(sess.id, tone):
            state = engine.fold()      # includes the auto-fired alarm
            await devices_ws.manager.send_to_device(station_id, {
                "type": "fold", "state": state})
            await devices_ws.manager.broadcast_to_instructors({
                "type": "device_event", "station_id": station_id,
                "event_type": "alarm.injected",
                "payload": {"tone": tone, "auto": True}, "state": state})
            return JSONResponse({"ok": True, "state": state, "via": "physiology"})
    state = engine.handle(type="alarm.injected", surface="instructor",
                          payload=payload)
    # Push to the device + firehose to other instructors.
    await devices_ws.manager.send_to_device(station_id, {
        "type": "inject", "tone": tone, "payload": payload, "state": state,
    })
    await devices_ws.manager.broadcast_to_instructors({
        "type": "device_event", "station_id": station_id,
        "event_type": "alarm.injected", "payload": payload, "state": state,
    })
    return JSONResponse({"ok": True, "state": state})


@router.post("/api/device/{station_id}/clear")
async def api_device_clear(
    station_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """V6 — instructor-side alarm clearing. Mirrors /inject. Body either
    `{tone: "..."}` to clear one alarm, or `{all: true}` to clear every
    active alarm on this device. Persists `alarm.cleared` event(s) and
    pushes the new state to the device + instructor firehose."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)   # M43 — multi-patient aware
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    clear_all = bool(body.get("all"))
    tone = (body.get("tone") or "").strip()
    if not clear_all and not tone:
        raise HTTPException(400, "Pass 'tone' or 'all: true'.")
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    state = engine.fold()
    targets: list[str] = []
    if clear_all:
        targets = [a.get("tone") for a in (state.get("active_alarms") or []) if a.get("tone")]
    else:
        targets = [tone]
    final_state = state
    for t in targets:
        final_state = engine.handle(type="alarm.cleared", surface="instructor",
                                     payload={"tone": t})
    await devices_ws.manager.send_to_device(station_id, {
        "type": "clear", "tones": targets, "state": final_state,
    })
    await devices_ws.manager.broadcast_to_instructors({
        "type": "device_event", "station_id": station_id,
        "event_type": "alarm.cleared", "payload": {"tones": targets},
        "state": final_state,
    })
    return JSONResponse({"ok": True, "cleared": targets, "state": final_state})


@router.post("/api/device/{station_id}/advance_time")
async def api_device_advance_time(
    station_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """V6.1 — instructor steps the device's internal clock forward by N
    minutes. Useful to skip the wait during training (e.g., infusion
    that would take 4 h to complete advances in seconds). Server calls
    engine.run_tick(now=now+N*60), which produces N-min worth of
    pump.tick events in one shot: VI advances, battery drains, alarms
    fire if thresholds are crossed (low_battery, infusion_complete).
    Broadcasts the new fold to the device for immediate re-render.

    Body: {"minutes": N}  (1 ≤ N ≤ 720)
    """
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)   # M43 — multi-patient aware
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    try:
        minutes = float(body.get("minutes", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid 'minutes' value.")
    if minutes <= 0 or minutes > 720:
        raise HTTPException(400, "'minutes' must be in (0, 720].")
    import time as _t
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    # V6.1 — operator's expectation: pressing +N hours subtracts EXACTLY
    # N hours from the displayed time-remaining. Earlier we tried to
    # "catch up" real elapsed time on top of the advance, which gave a
    # decrement larger than N. Now we explicitly set _last_tick to the
    # CURRENT real time so dt = N*60 exactly. The engine adds exactly
    # N minutes of infusion progress and the display drops by exactly
    # N hours. (The device's live interpolator handles real-time visual
    # ticking between user actions — it just doesn't accumulate into the
    # engine state until the next user-driven event.)
    engine._last_tick = _t.time()
    # Persist a discrete instructor action event for the transcript.
    from .engine import persistence as _persist
    _persist.record(sess.id, station_id,
                    type="device.time_advanced", surface="instructor",
                    payload={"minutes": minutes})
    state = engine.run_tick(now=_t.time() + minutes * 60)
    # V6.1.5 — work out whether anything actually moved. tick() short-
    # circuits when no channel is running, so the fold can be identical
    # to the pre-advance fold. In that case the device display won't
    # visibly change, which looks broken to the operator. We return an
    # `applied` flag so the UI can label the result, and we push a
    # discrete `time_advanced` toast to the device so the student SEES
    # that the operator pressed the button regardless of state.
    applied = False
    if state.get("channels"):
        applied = any((c or {}).get("running") for c in state["channels"].values())
    elif state.get("running"):
        applied = True
    # Push new fold to the device + firehose to operators.
    await devices_ws.manager.send_to_device(station_id, {
        "type": "fold", "state": state,
    })
    # Visible toast on the device chassis — fires for all device kinds.
    await devices_ws.manager.send_to_device(station_id, {
        "type": "time_advanced", "minutes": minutes, "applied": applied,
    })
    await devices_ws.manager.broadcast_to_instructors({
        "type": "device_event", "station_id": station_id,
        "event_type": "device.time_advanced",
        "payload": {"minutes": minutes, "applied": applied}, "state": state,
    })
    return JSONResponse({"ok": True, "minutes": minutes, "applied": applied,
                         "state": state})


@router.post("/api/device/{station_id}/assign")
async def api_device_assign(
    station_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)   # M43 — multi-patient aware
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    character_id = body.get("character_id") or None
    ehr_db.record_assignment(sess.id, station_id,
                             character_id=character_id, assigned_by="instructor")
    if station_id in sess.device_stations:
        sess.device_stations[station_id].character_id = character_id
    # Append a device.assigned event so the engine state reflects it.
    engine = make_engine(session_id=sess.id, station_id=station_id,
                         device_kind=station["device_kind"],
                         device_model=station["device_model"])
    state = engine.handle(type="device.assigned", surface="instructor",
                          payload={"character_id": character_id})
    await devices_ws.manager.send_to_device(station_id, {
        "type": "assign", "character_id": character_id, "state": state,
    })
    await devices_ws.manager.broadcast_to_instructors({
        "type": "device_assignment", "station_id": station_id,
        "character_id": character_id,
    })
    return JSONResponse({"ok": True, "character_id": character_id})


@router.get("/api/device/roster")
async def api_device_roster(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    join: str | None = None,
):
    """Snapshot of every DeviceStation in the (scoped) session.

    M43 — accepts `?join=<code>` so the ops view embedded in a v7
    encounter console gets ONLY that bed's device stations, not the
    union across all encounters. Without `join` falls back to the v6
    singleton (whose absence in multi-patient mode just returns an
    empty roster instead of failing).
    """
    sess = _session_for_join(join)
    if sess is None:
        return JSONResponse({"stations": []})
    # V6 — self-heal: if SQLite has device_station rows for this session
    # that aren't yet in memory (e.g. operator reopened the page after a
    # network blip, or the in-memory dict drifted), rehydrate them so the
    # roster shows every joined device.
    for db_row in ehr_db.device_stations(sess.id):
        sid = db_row["id"]
        if sid not in sess.device_stations:
            ds = sess.add_device_station(
                sid,
                device_kind=db_row["device_kind"],
                device_model=db_row["device_model"],
                label=db_row.get("label") or "",
                user_agent=db_row.get("user_agent") or "",
            )
            # Keep the persisted joined_at + last_seen so the online dot
            # reflects reality rather than "joined just now".
            ds.joined_at = db_row.get("joined_at") or ds.joined_at
            ds.last_seen = db_row.get("last_seen") or ds.last_seen
    # M59 bugfix #2 — Surface SHARED med carts on every linked
    # encounter's roster.  The M47 cart's `device_station` row is
    # owned by ONE encounter (its primary), but `room.cart_links[cid]`
    # may name several encounters.  Pre-fix, only the primary saw the
    # cart in its per-patient console's Devices block; secondary
    # linked encounters thought no cart existed even though the
    # Multi-Patient Control panel listed them as linked.
    #
    # Now: walk the active room's `cart_links` and, for any cart
    # whose link list contains THIS encounter and whose station is
    # owned by a DIFFERENT encounter, rehydrate that station into
    # `sess.device_stations` so the roster surfaces it. The
    # `_session_for_station` resolver already finds the right primary
    # for ops on the station, so dispense / inject / unlink continue
    # to route correctly.
    try:
        room = control_room.get_active_room()
    except Exception:  # noqa: BLE001
        room = None
    if room is not None:
        for cart_sid, link_list in (room.cart_links or {}).items():
            if sess.id in (link_list or []) and \
               cart_sid not in sess.device_stations:
                cart_db = ehr_db.get_device_station(cart_sid) or {}
                if not cart_db:
                    continue
                ds = sess.add_device_station(
                    cart_sid,
                    device_kind=cart_db.get("device_kind") or "cabinet",
                    device_model=cart_db.get("device_model") or "pyxis",
                    label=cart_db.get("label") or "",
                    user_agent=cart_db.get("user_agent") or "",
                )
                ds.joined_at = cart_db.get("joined_at") or ds.joined_at
                ds.last_seen = cart_db.get("last_seen") or ds.last_seen
    out = []
    import time as _time
    now_sec = _time.time()
    for sid, st in sess.device_stations.items():
        assignment = ehr_db.current_assignment(sid) or {}
        # V6 — quick fold for active_alarms so the operator card can show
        # live alarms + silenced badges + Clear buttons. ~few ms per station;
        # acceptable for a 2-3s polling cadence.
        try:
            eng = make_engine(session_id=sess.id, station_id=sid,
                              device_kind=st.device_kind,
                              device_model=st.device_model)
            state = eng.fold()
            alarms = [{
                "tone":          a.get("tone"),
                "silenced":      (a.get("silenced_until") or 0) > now_sec,
                "silenced_until": a.get("silenced_until") or 0,
                "remaining_s":   max(0, int((a.get("silenced_until") or 0) - now_sec)),
                "raised_at":     a.get("raised_at"),
                "source":        a.get("source"),
            } for a in (state.get("active_alarms") or [])]
            # V6.1.5 — running-channel summary so the operator can see why
            # advance_time might be a no-op on a particular device. Without
            # this the buttons silently fail (engine.tick short-circuits on
            # any non-running channel) and the operator can't tell why.
            running_chs: list[str] = []
            if state.get("channels"):
                running_chs = [k for k, c in state["channels"].items()
                                if (c or {}).get("running")]
                runtime = "running" if running_chs else (
                    "programmed" if any(((c or {}).get("vtbi_ml") or 0) > 0
                                          for c in state["channels"].values())
                    else "idle")
            elif st.device_kind == "pump_enteral":
                runtime = "running" if state.get("running") else (
                    "programmed" if (state.get("volume_ml") or 0) > 0 else "idle")
            else:
                runtime = "online"
        except Exception:
            alarms = []
            running_chs = []
            runtime = st.runtime_state
        out.append({
            "station_id":    sid,
            "device_kind":   st.device_kind,
            "device_model":  st.device_model,
            "label":         st.label,
            "online":        st.online,
            "runtime_state": runtime,       # ← V6.1.5 derived from fold
            "running_channels": running_chs, # ← which channels will advance
            "character_id":  assignment.get("character_id"),
            "active_alarms": alarms,
            "joined_at":     st.joined_at,
            "last_seen":     st.last_seen,
        })
    return JSONResponse({"session_state": sess.state, "stations": out})


@router.get("/api/device/{station_id}/vent/controls")
async def api_vent_controls(station_id: str):
    """FR-012 D5 — the ventilator control surface (mode + ranges + settings +
    numerics + set-vs-measured). Device-origin trust, like bootstrap/state."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    from portal import vent_state
    return JSONResponse(vent_state.controls_view(sess.id))


@router.post("/api/device/{station_id}/vent/set")
async def api_vent_set(station_id: str, request: Request):
    """FR-012 D5 — apply one ventilator control change: validate + step-snap
    (VC0), couple into patient physiology (VC1), re-evaluate vent alarms."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    param = (body.get("param") or "").strip()
    if not param:
        raise HTTPException(400, "Missing 'param'.")
    from portal import vent_state
    view, err = vent_state.apply_control(sess.id, param, body.get("value"))
    if err:
        raise HTTPException(400, err)
    await devices_ws.manager.send_to_device(station_id, {"type": "vent", "vent": view})
    await devices_ws.manager.broadcast_to_instructors({
        "type": "device_event", "station_id": station_id, "event_type": "vent.set",
        "payload": {"param": param, "value": body.get("value")}})
    return JSONResponse({"ok": True, "vent": view})


@router.post("/api/device/{station_id}/vent/maneuver")
async def api_vent_maneuver(station_id: str, request: Request):
    """FR-012 D5 — a diagnostic maneuver (insp_hold / exp_hold / o2_100)."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    from portal import vent_state
    result = vent_state.maneuver(sess.id, (body.get("kind") or "").strip())
    return JSONResponse({"ok": True, "result": result})


@router.get("/api/device/{station_id}/vent/faults")
async def api_vent_faults(
    station_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-012 D6 — the ventilator fault catalog + the currently-armed faults."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    from portal import vent_faults
    return JSONResponse({"catalog": vent_faults.catalog(),
                         "active": vent_faults.active(sess.id)})


@router.post("/api/device/{station_id}/vent/fault")
async def api_vent_fault(
    station_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-012 D6 — arm / clear a ventilator fault (instructor). The fault degrades
    the vent state (waveforms + alarms) and patient physiology; clearing it lets
    the coupling recover the patient."""
    station = ehr_db.get_device_station(station_id)
    if station is None:
        raise HTTPException(404, "Station not found.")
    sess = _session_for_station(station)
    if sess is None:
        raise HTTPException(409, "No active session linked to this device station.")
    body = await request.json()
    action = (body.get("action") or "arm").strip()
    fault_id = (body.get("fault_id") or "").strip()
    from portal import vent_faults, vent_state
    if action == "clear_all":
        vent_faults.clear_all(sess.id)
    elif action == "clear":
        vent_faults.clear(sess.id, fault_id)
    else:
        _active, err = vent_faults.arm(sess.id, fault_id)
        if err:
            raise HTTPException(400, err)
    try:
        await devices_ws.manager.send_to_device(
            station_id, {"type": "vent", "vent": vent_state.view(sess.id)})
        await devices_ws.manager.broadcast_to_instructors({
            "type": "device_event", "station_id": station_id, "event_type": "vent.fault",
            "payload": {"action": action, "fault_id": fault_id}})
    except Exception:  # noqa: BLE001 — push is best-effort
        pass
    return JSONResponse({"ok": True, "active": vent_faults.active(sess.id)})


@router.get("/api/device/models")
async def api_device_models():
    """List all device kinds + the models we have skins/specs for. Used
    by the operator's 'Add device' modal."""
    out = {}
    for kind in registry.KIND_DIRS:
        out[kind] = registry.available_models(kind)
    return JSONResponse(out)


# ──────────────────────────────────────────────────────────────────────
# WebSocket endpoints
# ──────────────────────────────────────────────────────────────────────

@ws_router.websocket("/ws/device/{station_id}")
async def ws_device(ws: WebSocket, station_id: str):
    await devices_ws.handle_device_ws(ws, station_id)


@ws_router.websocket("/ws/instructor")
async def ws_instructor(ws: WebSocket):
    await devices_ws.handle_instructor_ws(ws)
