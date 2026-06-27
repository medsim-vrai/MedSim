"""MEDSIM 3 portal — operator HTTP service.

V2 + V3 routes share one FastAPI app. V2 (chat stations, control wizard,
debrief, persona library) is unchanged. V3 adds the integrated EHR layer:
EHR station onboarding, append-only chart event log, hybrid comparison
engine, Charting-complete lock-in. See CLAUDE.md and Blueprint §9 for
the full route inventory.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import time
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote_plus as _quote_plus

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (
    activities, alarms as alarms_mod, auth, control_room, control_session,
    credentials, debrief as debrief_mod, ecg as ecg_mod,
    future_devices as future_devices_mod,
    intercom as intercom_mod, library, qrgen, runtime, scenarios, scenes,
    telemetry as telemetry_mod,
    ehr as ehr_registry, ehr_db, ehr_seed,
    voices, ws_room, vrai_faces,
)
from fastapi import WebSocket

PORTAL_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PORTAL_DIR / "templates"))

# Durable device mode (ADR-0028): serve the BUILT VRAI Faces app from the portal
# itself, so the tablet loads the app from the SAME origin as the api + speech
# WebSocket — one server, one cert, no separate vite :5173, no cross-origin bind.
# Enabled by VRAI_FACES_SERVE=portal (and the dist build present). Dev/HMR still
# uses the vite dev server (the Develop button); this is the deployed-device path.
_VRAI_DIST = PORTAL_DIR.parent / "vrai-faces" / "packages" / "core" / "dist"


def _portal_serves_app() -> bool:
    return (os.environ.get("VRAI_FACES_SERVE") or "").strip().lower() == "portal" \
        and (_VRAI_DIST / "index.html").is_file()

# V6 — cache-busting helper for static assets. Templates call
# {{ static_v('control_ops.js') }} and get back e.g. "/static/control_ops.js?v=1779581234"
# (mtime). Any edit to a JS or CSS file auto-busts every browser's cache —
# avoids the silent "old client running new server" failure mode we hit
# while iterating on the audio fix.
def _static_versioned(rel_path: str) -> str:
    rel_path = rel_path.lstrip("/")
    file_path = PORTAL_DIR / "static" / rel_path
    try:
        ver = int(file_path.stat().st_mtime)
    except OSError:
        ver = 0
    return f"/static/{rel_path}?v={ver}"

templates.env.globals["static_v"] = _static_versioned

CREDENTIAL_FIELDS: list[tuple[str, str, str]] = [
    ("ANTHROPIC_API_KEY", "Anthropic API key",
     "Required. Used by B6 router, B9 generator, B10 validators."),
    ("ELEVENLABS_API_KEY", "ElevenLabs API key",
     "Optional (V4). Enables neural character voices (Flash v2.5). "
     "Without it the system uses browser SpeechSynthesis."),
    ("VOYAGE_API_KEY", "Voyage embedding key",
     "Free tier — use this for B3 KB vector index."),
    ("OPENAI_API_KEY", "OpenAI embedding key",
     "Alternative embedding provider for B3."),
    ("DATABASE_URL", "Telemetry database URL",
     "Optional. Defaults to local SQLite under data/."),
]

app = FastAPI(title="medsim portal", docs_url=None, redoc_url=None)
# CORS — the VRAI Faces app is a separate origin (e.g. :5173) and calls the
# no-auth /api/face/* endpoints (binding GET, skin save). Credential-less, so
# cookie-gated operator routes stay protected (a cross-origin request can't send
# the session cookie). Local/LAN trust model (ADR-0017).
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(PORTAL_DIR / "static")), name="static")
# V3 — serves the EHR bundle subresources (data.jsx, ui.jsx, screens.jsx,
# app.jsx, catalog.json) directly. The index.html for each EHR is served
# by the route handler below so V3 can inject the bootstrap globals.
app.mount("/ehr-static", StaticFiles(directory=str(PORTAL_DIR / "ehr")), name="ehr_static")

# --- Durable device mode (ADR-0028): serve the BUILT VRAI Faces app -----------
# When VRAI_FACES_SERVE=portal and the dist build is present, the portal serves
# the avatar app itself. The tablet then loads the app, the /api/face/* binding,
# the /listen turn, AND the speech WebSocket all from ONE origin (this portal) —
# so there is ONE TLS cert and NO cross-origin fetch. This permanently ends the
# separate-vite (:5173) + dual-cert + cross-origin class of "binding fetch
# failed" / "connection not secure" failures. Dev/HMR still uses the vite dev
# server (the Develop button); this is the deployed-device path only.
if _portal_serves_app():
    # The app's hashed bundles + bundled models (Kokoro/MediaPipe/face topology)
    # all live under dist/assets and are referenced absolutely (vite base "/").
    app.mount("/assets", StaticFiles(directory=str(_VRAI_DIST / "assets")), name="vrai_assets")

    # SPA entry: any /face/<id> serves index.html; the app reads the path + query
    # client-side (parseLaunchUrl). No bare /face/<id> route exists elsewhere
    # (the portal's face routes are all /api/face, /qr/face, /portal/face).
    @app.get("/face/{character_id}", response_class=HTMLResponse, include_in_schema=False)
    async def vrai_app_entry(character_id: str) -> HTMLResponse:  # noqa: ARG001
        # COOP+COEP make the page CROSS-ORIGIN ISOLATED → SharedArrayBuffer is
        # available, which the on-device STT runtime needs: the only onnxruntime-web
        # wasm build is threaded (shared memory) and a no-WebGPU tablet has no other
        # backend (ADR-0026 device-pilot fix). Same-origin assets (the whole app +
        # /assets/ort + mediapipe + the bundled model) load fine under require-corp;
        # the one cross-origin asset (Kokoro via the SW) is re-served with CORP.
        return HTMLResponse(
            (_VRAI_DIST / "index.html").read_text(encoding="utf-8"),
            headers={
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Embedder-Policy": "require-corp",
            },
        )

    # Root PWA files the app references absolutely (service worker must be served
    # from the origin root for its scope; manifest + icons for Add-to-Home-Screen).
    def _vrai_dist_file(fname: str, media: str):  # noqa: ANN202
        async def _serve() -> Response:
            p = _VRAI_DIST / fname
            return FileResponse(str(p), media_type=media) if p.is_file() \
                else Response(status_code=404)
        return _serve

    for _vf_name, _vf_media in (
        ("app-sw.js", "text/javascript"),
        ("manifest.webmanifest", "application/manifest+json"),
        ("apple-touch-icon.png", "image/png"),
        ("icon-192.png", "image/png"),
        ("icon-512.png", "image/png"),
        ("icon-maskable-512.png", "image/png"),
    ):
        app.add_api_route(
            f"/{_vf_name}", _vrai_dist_file(_vf_name, _vf_media),
            methods=["GET"], include_in_schema=False,
        )

# V6 — device subsystem. Routes + WebSocket live in portal/devices/ and
# are attached here so the new feature is self-contained.
from .devices import routes as _device_routes   # noqa: E402
_device_routes.attach(app, templates)

# v8 — VRAI Faces avatar integration: launchable-character list, bind payload
# (portrait attach), and the speech WebSocket + speak path. Self-contained in
# portal/vrai_faces.py; attached here like the device subsystem.
vrai_faces.attach(app, templates)

# FR-001/002 — the instructor's medication board (doctor/pharmacist teaching loop).
from . import med_routes as _med_routes  # noqa: E402
_med_routes.attach(app)

# FR-008 S5 — staged-error instructor API (wizard + live controls).
from . import med_error_routes as _med_error_routes  # noqa: E402
_med_error_routes.attach(app)

# FR-009 H2 — shift-handoff instructor API (start/end/state of the handoff phase).
from . import handoff_routes as _handoff_routes  # noqa: E402
_handoff_routes.attach(app)

# ADR-0038 — room-local STT: the Mac transcribes for the audio-only stations
# (trainee audio crosses the LAN to THIS portal only; transcribed in memory,
# discarded). Warm the model off-thread so the first take doesn't pay the load.
from . import room_stt as _room_stt  # noqa: E402
_room_stt.attach(app)
_room_stt.warm_in_background()


# V7 — Activity catalog seed. Idempotent — only inserts rows missing
# from the DB. Runs on every server boot; safe.
@app.on_event("startup")
async def _seed_activity_catalog() -> None:
    try:
        activities.seed_builtins()
    except Exception as exc:  # noqa: BLE001 — never fatal at boot
        import sys
        print(f"  [warn] activities.seed_builtins failed: {exc}",
              file=sys.stderr, flush=True)


@app.on_event("startup")
async def _resume_session_state() -> None:
    """FR-011 G1 (ADR-0039) — restore the last session on boot so a restart /
    crash / pause resumes instead of wiping. Off with MEDSIM_RESUME=0."""
    if (os.environ.get("MEDSIM_RESUME") or "1").strip() == "0":
        return
    try:
        from . import session_state
        summary = session_state.resume()
        if summary:
            print(f"  [resume] restored last session "
                  f"({summary.get('n_encounters')} encounter(s): "
                  f"{', '.join(n for n in (summary.get('names') or []) if n)})",
                  flush=True)
    except Exception as exc:  # noqa: BLE001 — never fatal at boot
        import sys
        print(f"  [warn] session resume failed (clean start): {exc}",
              file=sys.stderr, flush=True)


@app.on_event("shutdown")
async def _persist_session_state() -> None:
    """FR-011 G1 — on a graceful restart (SIGTERM), snapshot the live session so
    the next boot resumes it. PHI-free structured state only (ADR-0014)."""
    try:
        from . import session_state
        if session_state.persist():
            print("  [persist] session state saved for resume", flush=True)
    except Exception:  # noqa: BLE001 — never block shutdown
        pass


@app.exception_handler(HTTPException)
async def auth_redirect_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login?error=expired", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _default_landing() -> str:
    """Where a logged-in operator lands. The classic home stays the out-of-box
    default; the v7.1 'card launch' sets MEDSIM_DEFAULT_VIEW=console to boot straight
    into the Mission Control card system instead. Classic is always reachable — the
    card UI has 'Switch to classic control room', and the classic nav links to the
    card system the other way."""
    import os as _os
    v = (_os.environ.get("MEDSIM_DEFAULT_VIEW") or "").strip().lower()
    if v in ("console", "cards", "card", "mission", "v8", "7.1"):
        # Land on SET UP, not Operate — a fresh launch has no live session, and
        # opening straight into Operations (empty/stale) is confusing. Start where
        # you build the session.
        return "/portal/console?mode=setup"
    return "/portal/home"


@app.get("/", response_class=HTMLResponse)
async def root(medsim_session: Annotated[str | None, Cookie()] = None):
    if auth.verify_session(medsim_session):
        return RedirectResponse(_default_landing(), status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request, "login.html",
        {"initialized": credentials.is_initialized(), "error": error},
    )


@app.post("/login")
async def login_submit(password: Annotated[str, Form()],
                        role: Annotated[str, Form()] = "instructor"):
    """M18 — `role` form field defaults to 'instructor'; pass
    'observer' for the read-only TA / preceptor seat. The observer
    can view every dashboard / debrief page but their cookie is
    rejected by every mutating route."""
    if not credentials.is_initialized():
        return RedirectResponse("/login?error=not-initialized", status_code=303)
    try:
        vault = credentials.unlock(password)
    except (ValueError, FileNotFoundError):
        return RedirectResponse("/login?error=invalid", status_code=303)
    response = RedirectResponse(_default_landing(), status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_session_token(vault, role=role),
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/initialize")
async def initialize_submit(
    password: Annotated[str, Form()],
    confirm: Annotated[str, Form()],
):
    if password != confirm:
        return RedirectResponse("/login?error=mismatch", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/login?error=length", status_code=303)
    if credentials.is_initialized():
        return RedirectResponse("/login?error=exists", status_code=303)
    credentials.initialize(password)
    vault = credentials.unlock(password)
    response = RedirectResponse(_default_landing(), status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue_session_token(vault),
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout(medsim_session: Annotated[str | None, Cookie()] = None):
    auth.clear_session(medsim_session)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response


# ---------------------------------------------------------------------------
# Home / status
# ---------------------------------------------------------------------------

@app.get("/portal", response_class=HTMLResponse)
async def portal_root(medsim_session: Annotated[str | None, Cookie()] = None):
    if auth.verify_session(medsim_session):
        return RedirectResponse(_default_landing(), status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/portal/home", response_class=HTMLResponse)
async def home_page(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    stored = vault.credentials
    voyage = bool(stored.get("VOYAGE_API_KEY"))
    openai_set = bool(stored.get("OPENAI_API_KEY"))
    scen_list = scenarios.list_scenarios()
    char_list = scenarios.list_characters()
    ready = {
        "anthropic": bool(stored.get("ANTHROPIC_API_KEY")),
        "embedding": voyage or openai_set,
        "embedding_provider": "Voyage" if voyage else ("OpenAI" if openai_set else None),
        "scenarios": bool(scen_list),
        "characters": bool(char_list),
    }
    counts = {"scenarios": len(scen_list), "characters": len(char_list)}
    return templates.TemplateResponse(
        request, "home.html",
        {"active": "home", "ready": ready, "counts": counts},
    )


@app.get("/portal/console", response_class=HTMLResponse)
async def mission_control_console(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    mode: str = "operate",
):
    """FR-011 G3 — Mission Control: the 3-mode GUI shell (Set up · Operate ·
    Debrief) over the SAME portal APIs, with a persistent readiness bar (G2) and
    a 'Switch to classic control room' link on every screen. The classic room
    stays the default; G4-G6 fill the mode panels. Mode lives in the URL."""
    if mode not in ("setup", "operate", "debrief"):
        mode = "operate"
    # FR-011 G5 — bootstrap the Launch Wizard from the SAME catalogs the classic
    # control room uses (each sample carries its FULL persona roster), so there's
    # no divergent data source. The sample + EHR <option>s are rendered SERVER-SIDE
    # (so the pickers work even with stale/blocked console.js); the JSON blob below
    # carries the full sample objects (for roster auto-fill) + the persona catalog.
    persona_recs = library.list_personas()
    by_id = {p["id"]: p for p in persona_recs}

    def _patient_of(sample):
        # Each sample's patient = its persona with roleGroup "Patient" (exactly one
        # in the catalog); used so picking a scenario for a bed picks its patient.
        for pid in (sample.get("personas") or []):
            if (by_id.get(pid, {}).get("roleGroup") or "") == "Patient":
                return pid
        ids = sample.get("personas") or []
        return ids[0] if ids else None

    samples = []
    for s in library.list_sample_scenarios():
        s2 = dict(s)
        s2["patient_id"] = _patient_of(s)
        samples.append(s2)
    # FR-011 #51 — PARITY WITH CLASSIC SETUP: /portal/control/setup also lists saved
    # v1 YAML scenarios (scenarios/*.yaml). Surface them here too so the wizard and
    # the classic room never show a different set. v1 has no v2 persona roster, so
    # there's no auto-patient/cast — the bed proceeds with manually-picked characters;
    # flagged `legacy` so the picker can label it. (No-op when scenarios/ is empty.)
    for v in scenarios.list_scenarios():
        if v.get("error"):
            continue
        samples.append({
            "id": "v1:" + str(v.get("id") or ""),
            "name": v.get("name") or v.get("id") or "Untitled (v1)",
            "personas": [],
            "patient_id": None,
            "scenario_text": v.get("patient_summary") or "",
            "legacy": True,
        })
    ehrs = [{"id": e["id"], "name": e["name"]} for e in ehr_registry.REGISTRY]
    default_ehr = ehr_registry.default_id()
    personas = [
        {"id": p["id"], "name": p.get("name", ""), "role": p.get("role", ""),
         "roleGroup": p.get("roleGroup", ""),
         # current portrait/skin assignment (drives the wizard's image picker;
         # one image serves the flat audio portrait AND the 3D rig source photo)
         "avatar_skin": vrai_faces.assigned_skin_id(p["id"]) or ""}
        for p in persona_recs
    ]
    skins = vrai_faces.list_skins()
    # Device catalog for the wizard's Devices step (Basic vs Advanced), built from
    # the SAME registry the control room uses — kind + default model + group.
    from portal.devices import registry as _dev_reg
    _dev_labels = {
        "pump_iv": "IV pump", "pump_enteral": "Enteral pump",
        "cabinet": "Med cart", "patient_integrated_alarm": "Integrated Com & Alarm",
        "telemetry_monitor": "Telemetry monitor", "vent_monitor": "Vent monitor",
        "ventilator": "Ventilator (controls)",
    }
    _dev_advanced = {"telemetry_monitor", "vent_monitor", "ventilator"}
    _dev_common = {"cabinet"}      # the med cart is a shared/common device, not per-bed
    devices_catalog = []
    for k in _dev_reg.list_kinds():
        models = _dev_reg.REFERENCE_MODELS.get(k) or []
        devices_catalog.append({
            "kind": k, "name": _dev_labels.get(k, k),
            "group": "Advanced" if k in _dev_advanced else "Basic",
            "common": k in _dev_common,
            "model": models[0] if models else "",
            "models": models,   # full list so the wizard popup can offer model/brand choice
        })

    bootstrap = {"samples": samples, "ehrs": ehrs, "default_ehr": default_ehr,
                 "personas": personas, "devices": devices_catalog, "skins": skins}
    return templates.TemplateResponse(request, "console.html", {
        "mode": mode, "bootstrap": bootstrap,
        "samples": samples, "ehrs": ehrs, "default_ehr": default_ehr})


@app.post("/portal/examples/load")
async def load_examples(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    created = scenarios.load_examples()
    parts = []
    if created["characters"]:
        parts.append(f"Created {len(created['characters'])} character(s): {', '.join(created['characters'])}.")
    if created["scenarios"]:
        parts.append(f"Created {len(created['scenarios'])} scenario(s): {', '.join(created['scenarios'])}.")
    if not parts:
        parts.append("Nothing to create — example files already exist.")
    return JSONResponse({"ok": True, "message": " ".join(parts)})


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

@app.get("/portal/credentials", response_class=HTMLResponse)
async def credentials_page(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    stored = vault.credentials
    rows = []
    for key, label, hint in CREDENTIAL_FIELDS:
        value = stored.get(key, "")
        rows.append({
            "key": key, "label": label, "hint": hint,
            "set": bool(value), "preview": _mask(value),
        })
    return templates.TemplateResponse(
        request, "credentials.html",
        {"active": "credentials", "fields": rows},
    )


@app.post("/portal/credentials")
async def credentials_save(
    key: Annotated[str, Form()],
    value: Annotated[str, Form()],
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    known = {k for k, _, _ in CREDENTIAL_FIELDS}
    if key not in known:
        raise HTTPException(400, f"Unknown credential key: {key}")
    if value.strip():
        vault.set(key, value.strip())
    else:
        vault.delete(key)
    # M38 — refresh the process-wide cache so station-turn routes pick
    # up the new Anthropic key without restarting the room.
    if key == "ANTHROPIC_API_KEY":
        _capture_anthropic_key(value.strip() if value.strip() else "")
    return RedirectResponse("/portal/credentials", status_code=303)


@app.post("/portal/credentials/test")
async def credentials_test(
    key: Annotated[str, Form()],
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    value = vault.get(key)
    if not value:
        return JSONResponse({"ok": False, "message": "Not set."})
    if key == "ANTHROPIC_API_KEY":
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=value)
            client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1,
                messages=[{"role": "user", "content": "ok"}],
            )
            return JSONResponse({"ok": True, "message": "Anthropic API key accepted."})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "message": f"{type(exc).__name__}: {exc}"})
    if key == "ELEVENLABS_API_KEY":
        h = voices.health(value)
        if h["available"]:
            return JSONResponse({"ok": True,
                "message": f"ElevenLabs OK — {h['voice_count']} voices, model {h['model']}."})
        return JSONResponse({"ok": False, "message": f"ElevenLabs unreachable: {h['detail']}"})
    return JSONResponse({"ok": True, "message": "Stored. No live test handler for this key yet."})


# ---------------------------------------------------------------------------
# Scenarios — CRUD
# ---------------------------------------------------------------------------

@app.get("/portal/scenarios", response_class=HTMLResponse)
async def scenarios_list(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    # V8 — resolve each scenario's characters to {id, name, has_avatar} so the
    # card can show a per-character avatar QR + whether an avatar is assigned.
    scens = scenarios.list_scenarios()
    for s in scens:
        s["characters_detail"] = [
            {
                "id": cid,
                "name": (vrai_faces.resolve_card(cid) or {}).get("name") or cid,
                "has_avatar": vrai_faces.has_portrait(cid),
            }
            for cid in (s.get("characters") or [])
        ]
    return templates.TemplateResponse(
        request, "scenarios.html",
        {"active": "scenarios", "scenarios": scens},
    )


# ── Avatar skin library (V8) ───────────────────────────────────────────
# Save a face once (labeled), then assign it to any character/persona instead
# of re-importing each time. Assigning copies the image into face_portraits/.

@app.get("/portal/skins", response_class=HTMLResponse)
async def skins_page(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Avatar skin library — saved labeled portraits, assignable to any
    character or persona."""
    targets: list[dict[str, str]] = []
    seen: set[str] = set()
    for c in scenarios.list_characters():
        cid = str(c.get("id") or "")
        if cid and cid not in seen:
            seen.add(cid)
            targets.append({"id": cid, "name": f"{c.get('name') or cid} · character"})
    for p in library.list_personas():
        pid = str(p.get("id") or "")
        if pid and pid not in seen:
            seen.add(pid)
            targets.append({"id": pid, "name": f"{p.get('name') or pid} · persona"})
    return templates.TemplateResponse(
        request, "skins.html",
        {
            "active": "skins",
            "skins": vrai_faces.list_skins(),
            "targets": targets,
            "saved": request.query_params.get("saved"),
            "assigned": request.query_params.get("assigned"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/portal/skins")
async def skins_upload(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    label: Annotated[str, Form()] = "",
    image: UploadFile = File(...),
):
    """Save an uploaded portrait as a labeled skin."""
    data = await image.read()
    if not data:
        return RedirectResponse("/portal/skins?error=empty", status_code=303)
    if len(data) > 8 * 1024 * 1024:
        return RedirectResponse("/portal/skins?error=toobig", status_code=303)
    fn = image.filename or ""
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "png"
    skin = vrai_faces.save_skin(label, data, ext)
    return RedirectResponse(
        f"/portal/skins?saved={_quote_plus(skin['label'])}", status_code=303)


@app.get("/portal/skins/{skin_id}/image")
async def skins_image(
    skin_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    p = vrai_faces.skin_image_path(skin_id)
    if p is None:
        raise HTTPException(404, "skin not found")
    return FileResponse(str(p))


@app.post("/portal/skins/{skin_id}/assign")
async def skins_assign(
    skin_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    character_id: Annotated[str, Form()],
):
    ok = vrai_faces.assign_skin(skin_id, character_id)
    qs = f"assigned={_quote_plus(character_id)}" if ok else "error=assign"
    return RedirectResponse(f"/portal/skins?{qs}", status_code=303)


@app.post("/portal/skins/{skin_id}/delete")
async def skins_delete(
    skin_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    vrai_faces.delete_skin(skin_id)
    return RedirectResponse("/portal/skins", status_code=303)


@app.get("/portal/scenarios/new", response_class=HTMLResponse)
async def scenario_new(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return templates.TemplateResponse(
        request, "scenario_form.html",
        {
            "active": "scenarios",
            "scenario": _normalize_scenario(None),
            "all_characters": scenarios.list_characters(),
            "action": "/portal/scenarios",
            "is_edit": False,
        },
    )


@app.get("/portal/scenario-studio", response_class=HTMLResponse)
async def scenario_studio_page(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-013b — Scenario Studio: a guided page (reached from Set up) that prompts
    the instructor for a premise + patient + LOCAL factors, drafts a full scenario
    via Claude, and (after review/edit) saves it as a first-class launch-wizard
    scenario. Active local-context items + the inline local factors ground the
    draft in this site's practice."""
    from . import local_context as _lc
    patients = [{"id": p["id"], "name": p.get("name", ""), "role": p.get("role", "")}
                for p in library.list_personas()
                if (p.get("roleGroup") or "") == "Patient"]
    return templates.TemplateResponse(request, "scenario_studio.html", {
        "active": "console", "patients": patients,
        "active_overlay_count": len(_lc.active_items()),
    })


@app.get("/portal/scenarios/{scenario_id}/edit", response_class=HTMLResponse)
async def scenario_edit(
    scenario_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    data = scenarios.get_scenario(scenario_id)
    if data is None:
        return RedirectResponse("/portal/scenarios", status_code=303)
    return templates.TemplateResponse(
        request, "scenario_form.html",
        {
            "active": "scenarios",
            "scenario": _normalize_scenario(data),
            "all_characters": scenarios.list_characters(),
            "action": f"/portal/scenarios?old_id={scenario_id}",
            "is_edit": True,
        },
    )


@app.post("/portal/scenarios")
async def scenario_save(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    old_id: str | None = None,
):
    form = await request.form()
    data = _build_scenario_from_form(form)
    scenarios.save_scenario(data, old_id=old_id)
    return RedirectResponse("/portal/scenarios", status_code=303)


@app.post("/portal/scenarios/{scenario_id}/delete")
async def scenario_delete(
    scenario_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    scenarios.delete_scenario(scenario_id)
    return RedirectResponse("/portal/scenarios", status_code=303)


@app.post("/portal/scenarios/{scenario_id}/duplicate")
async def scenario_duplicate(
    scenario_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    scenarios.duplicate_scenario(scenario_id)
    return RedirectResponse("/portal/scenarios", status_code=303)


@app.post("/portal/scenarios/{scenario_id}/launch")
async def scenario_launch(
    scenario_id: str,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Start a real working chat session with the scenario's characters.

    This is a v0 of the runtime — replace with the proper B5 orchestrator
    when that block lands.
    """
    api_key = vault.get("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({
            "ok": False,
            "message": "Anthropic API key required. Add it on the Credentials tab.",
        })
    scen = scenarios.get_scenario(scenario_id)
    if scen is None:
        return JSONResponse({
            "ok": False,
            "message": f"Scenario '{scenario_id}' not found.",
        })
    if not (scen.get("characters") or []):
        return JSONResponse({
            "ok": False,
            "message": "This scenario has no characters assigned. Edit it and add characters first.",
        })
    sess = runtime.create_session(scenario_id, api_key)
    if sess is None:
        return JSONResponse({
            "ok": False,
            "message": (
                "Could not start session. The scenario references character "
                "IDs that don't exist — open the scenario, check the "
                "Characters section, and save."
            ),
        })
    return JSONResponse({
        "ok": True,
        "session_id": sess.id,
        "redirect_url": f"/portal/session/{sess.id}",
    })


# ---------------------------------------------------------------------------
# Session — the working chat runtime (v0 of B5+B6+B9)
# ---------------------------------------------------------------------------

@app.get("/portal/session/{session_id}", response_class=HTMLResponse)
async def session_page(
    session_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    sess = runtime.get_session(session_id)
    if sess is None:
        return RedirectResponse("/portal/scenarios", status_code=303)
    return templates.TemplateResponse(
        request, "session.html",
        {
            "active": "scenarios",
            "session": sess,
            "patient_summary": _patient_one_line(sess.scenario.get("patient", {}) or {}),
        },
    )


@app.post("/portal/session/{session_id}/turn")
async def session_turn(
    session_id: str,
    addressee: Annotated[str, Form()],
    message: Annotated[str, Form()],
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    result = runtime.take_turn(session_id, addressee, message)
    return JSONResponse(result)


@app.post("/portal/session/{session_id}/end")
async def session_end(
    session_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    runtime.end_session(session_id)
    return RedirectResponse("/portal/scenarios", status_code=303)


@app.get("/portal/session/{session_id}/voice", response_class=HTMLResponse)
async def session_voice_page(
    session_id: str,
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """v2/v4 — voice-enabled chat: STT in, TTS out, per-character voices.

    V4: each character can be given an ElevenLabs neural voice; the
    legacy browser SpeechSynthesis path remains the fallback.
    """
    sess = runtime.get_session(session_id)
    if sess is None:
        return RedirectResponse("/portal/scenarios", status_code=303)
    # Resolve the ElevenLabs key — this also primes voices._runtime_key so
    # the (unauthenticated) /api/tts route can synthesize for this page.
    el_key = voices.get_api_key(vault)
    _gender_to_sex = {"male": "M", "female": "F"}
    chars_for_js: list[dict[str, Any]] = []
    for cid, char in sess.characters.items():
        vp = char.get("voice_profile") or {}
        chars_for_js.append({
            "id": cid,
            "name": char.get("name", cid),
            "role": char.get("role", ""),
            "voice_profile": vp,
            # Inferred traits for the V4 voice picker. V1 characters have
            # no age — default to middle_aged.
            "sex": _gender_to_sex.get((vp.get("gender") or "").lower(), "U"),
            "age_band": "middle_aged",
        })
    return templates.TemplateResponse(
        request, "session_voice.html",
        {
            "active": "scenarios",
            "session": sess,
            "patient_summary": _patient_one_line(sess.scenario.get("patient", {}) or {}),
            "characters_for_js": chars_for_js,
            "elevenlabs_available": bool(el_key),
        },
    )


# ---------------------------------------------------------------------------
# Characters — CRUD
# ---------------------------------------------------------------------------

@app.get("/portal/characters", response_class=HTMLResponse)
async def characters_list(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return templates.TemplateResponse(
        request, "characters.html",
        {"active": "characters", "characters": scenarios.list_characters()},
    )


@app.get("/portal/characters/new", response_class=HTMLResponse)
async def character_new(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return templates.TemplateResponse(
        request, "character_form.html",
        {
            "active": "characters",
            "character": _normalize_character(None),
            "action": "/portal/characters",
            "is_edit": False,
        },
    )


@app.get("/portal/characters/{character_id}/edit", response_class=HTMLResponse)
async def character_edit(
    character_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    data = scenarios.get_character(character_id)
    if data is None:
        return RedirectResponse("/portal/characters", status_code=303)
    return templates.TemplateResponse(
        request, "character_form.html",
        {
            "active": "characters",
            "character": _normalize_character(data),
            "action": f"/portal/characters?old_id={character_id}",
            "is_edit": True,
        },
    )


@app.post("/portal/characters")
async def character_save(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    old_id: str | None = None,
):
    form = await request.form()
    data = _build_character_from_form(form)
    scenarios.save_character(data, old_id=old_id)
    return RedirectResponse("/portal/characters", status_code=303)


@app.post("/portal/characters/{character_id}/delete")
async def character_delete(
    character_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    scenarios.delete_character(character_id)
    return RedirectResponse("/portal/characters", status_code=303)


@app.post("/portal/characters/{character_id}/duplicate")
async def character_duplicate(
    character_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    scenarios.duplicate_character(character_id)
    return RedirectResponse("/portal/characters", status_code=303)


# ---------------------------------------------------------------------------
# Live dashboard / debriefs — placeholders until B5/B12 land
# ---------------------------------------------------------------------------

@app.get("/portal/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return templates.TemplateResponse(
        request, "dashboard.html", {"active": "dashboard"}
    )


@app.get("/portal/debrief", response_class=HTMLResponse)
async def debrief_list(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """List view — all saved debriefs plus a 'current session' card if a
    live session has any transcript."""
    active = control_session.get_active()
    has_live = bool(active and active.transcript)
    return templates.TemplateResponse(
        request, "debrief.html",
        {
            "active": "debrief",
            "debriefs": debrief_mod.list_saved(),
            "has_live": has_live,
            "live_session_id": active.id if has_live else None,
            "live_scenario_name": active.scenario_name if has_live else None,
            "live_turn_count": len(active.transcript) if has_live else 0,
        },
    )


@app.get("/portal/debrief/current", response_class=HTMLResponse)
async def debrief_current(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Render the debrief for the currently-active session (computed live,
    not saved). Useful for previewing before the operator ends the session."""
    sess = control_session.get_active()
    if sess is None or not sess.transcript:
        return RedirectResponse("/portal/debrief", status_code=303)
    db = debrief_mod.build(sess)
    return templates.TemplateResponse(
        request, "debrief_detail.html",
        {"active": "debrief", "debrief": db, "is_live": True},
    )


@app.get("/portal/debrief/{session_id}", response_class=HTMLResponse)
async def debrief_detail(
    session_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    db = debrief_mod.load(session_id)
    if db is None:
        return RedirectResponse("/portal/debrief", status_code=303)
    return templates.TemplateResponse(
        request, "debrief_detail.html",
        {"active": "debrief", "debrief": db, "is_live": False},
    )


@app.get("/api/debrief/{session_id}")
async def api_debrief_json(
    session_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    db = debrief_mod.load(session_id)
    if db is None:
        raise HTTPException(404, "Debrief not found")
    return JSONResponse(db)


@app.get("/health")
async def health():
    return {"ok": True, "vault_initialized": credentials.is_initialized()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * 8 + value[-4:]


def _patient_one_line(patient: dict[str, Any]) -> str:
    parts = []
    if patient.get("age") not in (None, ""):
        parts.append(f"{patient['age']}y")
    if patient.get("sex"):
        parts.append(str(patient["sex"]))
    if patient.get("history"):
        h = str(patient["history"])
        parts.append(h[:90] + ("…" if len(h) > 90 else ""))
    return " · ".join(parts)


def _lines_to_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _lines_to_dict(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k:
                out[k] = v
    return out


def _normalize_scenario(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    patient = data.get("patient") or {}
    curriculum = data.get("curriculum") or {}
    return {
        "id": data.get("id", "") or "",
        "name": data.get("name", "") or "",
        "patient": {
            "age": patient.get("age", "") if patient.get("age") is not None else "",
            "sex": patient.get("sex", "") or "",
            "history": patient.get("history", "") or "",
            "baseline_vitals": patient.get("baseline_vitals", {}) or {},
        },
        "characters": data.get("characters", []) or [],
        "curriculum": {
            "touchpoints": curriculum.get("touchpoints", []) or [],
            "unlocked": curriculum.get("unlocked", []) or [],
        },
        "allowed_tools": data.get("allowed_tools", []) or [],
        "kb_scope": data.get("kb_scope", []) or [],
    }


def _normalize_character(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    identity = data.get("identity") or {}
    voice = data.get("voice") or {}
    return {
        "id": data.get("id", "") or "",
        "name": data.get("name", "") or "",
        "role": data.get("role", "") or "",
        "identity": {
            "years_experience": identity.get("years_experience", "") if identity.get("years_experience") is not None else "",
            "training_site": identity.get("training_site", "") or "",
            "shift": identity.get("shift", "") or "",
            "mood_today": identity.get("mood_today", "") or "",
        },
        "voice": {
            "register": voice.get("register", "") or "",
            "sentence_length": voice.get("sentence_length", "short") or "short",
            "examples": voice.get("examples", []) or [],
            "never_says": voice.get("never_says", []) or [],
        },
        "knowledge_boundary": data.get("knowledge_boundary", "") or "",
        "teaching_stance": data.get("teaching_stance", "") or "",
        "scope_of_action": data.get("scope_of_action", []) or [],
        "scene_contract": data.get("scene_contract", []) or [],
    }


def _build_scenario_from_form(form) -> dict[str, Any]:
    name = (form.get("name") or "").strip()
    sid = (form.get("id") or "").strip() or scenarios.slugify(name)
    characters = form.getlist("characters") if hasattr(form, "getlist") else []
    age_str = (form.get("patient_age") or "").strip()
    return {
        "id": sid,
        "name": name,
        "patient": {
            "age": int(age_str) if age_str.isdigit() else (age_str or None),
            "sex": (form.get("patient_sex") or "").strip(),
            "history": (form.get("patient_history") or "").strip(),
            "baseline_vitals": _lines_to_dict(form.get("patient_vitals")),
        },
        "characters": [c for c in characters if c],
        "curriculum": {
            "touchpoints": _lines_to_list(form.get("touchpoints")),
            "unlocked": _lines_to_list(form.get("unlocked")),
        },
        "allowed_tools": _lines_to_list(form.get("allowed_tools")),
        "kb_scope": _lines_to_list(form.get("kb_scope")),
    }


def _build_character_from_form(form) -> dict[str, Any]:
    name = (form.get("name") or "").strip()
    cid = (form.get("id") or "").strip() or scenarios.slugify(name)
    years_str = (form.get("years_experience") or "").strip()
    return {
        "id": cid,
        "name": name,
        "role": (form.get("role") or "").strip(),
        "identity": {
            "years_experience": int(years_str) if years_str.isdigit() else None,
            "training_site": (form.get("training_site") or "").strip(),
            "shift": (form.get("shift") or "").strip(),
            "mood_today": (form.get("mood_today") or "").strip(),
        },
        "voice": {
            "register": (form.get("voice_register") or "").strip(),
            "sentence_length": (form.get("voice_sentence_length") or "short").strip(),
            "examples": _lines_to_list(form.get("voice_examples")),
            "never_says": _lines_to_list(form.get("voice_never_says")),
        },
        "knowledge_boundary": (form.get("knowledge_boundary") or "").strip(),
        "teaching_stance": (form.get("teaching_stance") or "").strip(),
        "scope_of_action": _lines_to_list(form.get("scope_of_action")),
        "scene_contract": _lines_to_list(form.get("scene_contract")),
    }


# ===========================================================================
# MEDSIM 2 ADDITIONS — Control room, QR onboarding, persona library, stations
# ===========================================================================

def _lan_ip() -> str:
    """Best-effort LAN IP — matches run_portal._lan_ip."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _public_host() -> str:
    """A STABLE hostname for the portal across networks/locations (ADR-0030).

    When MEDSIM_PUBLIC_HOST is set (e.g. 'portal.medsim.lan'), every QR / device
    URL targets the NAME instead of the auto-detected LAN IP — so a DHCP or
    between-locations IP change never breaks the cert or a baked QR (the cert is
    issued for the name). Requires the name to RESOLVE: a gateway DNS record for
    the fleet, or an /etc/hosts entry for local Mac testing. Unset → the prior
    LAN-IP behavior, unchanged (opt-in, no regression)."""
    return (os.environ.get("MEDSIM_PUBLIC_HOST") or "").strip()


def _base_url_for_qr(request: Request) -> str:
    """Build a URL that mobile devices on the same LAN can reach.

    MEDSIM_PUBLIC_HOST (if set) wins — a stable name that survives IP changes.
    Otherwise prefers the request's host header (which may be a LAN IP if the
    operator is already on iPad mode); falls back to detecting the LAN IP.
    """
    scheme = request.url.scheme or "http"
    port = request.url.port
    host = _public_host()
    if not host:
        host = request.url.hostname or ""
        if host in ("127.0.0.1", "localhost", ""):
            host = _lan_ip()
    if port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


# ----- Personas library viewer --------------------------------------------

@app.get("/portal/personas", response_class=HTMLResponse)
async def personas_page(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    # Shallow-copy each persona (library dicts may be cached) and annotate the
    # currently-assigned avatar skin, so the picker can highlight it.
    personas = [
        {**p, "avatar_skin": vrai_faces.assigned_skin_id(str(p.get("id") or ""))}
        for p in library.list_personas()
    ]
    return templates.TemplateResponse(
        request, "personas.html",
        {
            "active": "personas",
            "personas": personas,
            "behavioral_dimensions": library.behavioral_dimensions(),
            "skins": vrai_faces.list_skins(),
        },
    )


@app.post("/portal/personas/{persona_id}/avatar")
async def persona_avatar_assign(
    persona_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    skin_id: Annotated[str, Form()] = "",
):
    """Activate/select this persona's avatar from the skin library (empty
    skin_id clears it). Redirects back to the personas page."""
    if skin_id.strip():
        vrai_faces.assign_skin(skin_id.strip(), persona_id)
    else:
        vrai_faces.clear_portrait(persona_id)
    return RedirectResponse("/portal/personas", status_code=303)


# ----- Curriculum modules viewer ------------------------------------------

@app.get("/portal/curriculum", response_class=HTMLResponse)
async def curriculum_page(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return templates.TemplateResponse(
        request, "curriculum.html",
        {
            "active": "curriculum",
            "modules": library.list_modules(),
            "programs": library.list_programs(),
        },
    )


@app.get("/api/modules")
async def api_modules(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return JSONResponse({"modules": library.list_modules()})


@app.get("/api/programs")
async def api_programs(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return JSONResponse({"programs": library.list_programs()})


@app.get("/api/personas")
async def api_personas(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return JSONResponse({
        "personas": library.list_personas(),
        "behavioral_dimensions": library.behavioral_dimensions(),
    })


# ----- QR code endpoint ---------------------------------------------------

@app.get("/api/qr.svg")
async def api_qr_svg(data: str, scale: int = 6):
    """Returns an SVG QR code encoding `data`. Open to all (no auth) so the
    control-room wizard's <img> tags can fetch without cookies, and the
    join URL can be reached from the mobile device too."""
    svg = qrgen.make_qr_svg(data, scale=scale)
    return Response(content=svg, media_type="image/svg+xml")


# ----- Control room wizard -----------------------------------------------

@app.get("/portal/control", response_class=HTMLResponse)
async def control_wizard(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    # V7 — control_session.get_active() raises when a multi-encounter
    # room is active (M2/M3 safety: v6 callers must not silently grab
    # the first encounter). The wizard's "active_session" hint is only
    # meaningful for the single-patient path; in room-mode the
    # dashboard is the right surface. Treat the raise as "no
    # single-patient session active" and let the wizard render.
    try:
        active = control_session.get_active()
    except RuntimeError:
        active = None
    # v1 scenarios — name + summary only; their character refs don't map to
    # v2 personas so we only auto-fill name + a derived notes string.
    v1_scens = []
    for s in scenarios.list_scenarios():
        if s.get("error"):
            continue
        v1_scens.append({
            "id": s["id"],
            "name": s["name"],
            "patient_summary": s.get("patient_summary", ""),
        })
    return templates.TemplateResponse(
        request, "control.html",
        {
            "active": "control",
            # Annotate each persona with its currently-assigned avatar skin so the
            # encounter-authoring grid can show the picker default.
            "personas": [
                {**p, "avatar_skin": vrai_faces.assigned_skin_id(str(p.get("id") or ""))}
                for p in library.list_personas()
            ],
            "avatar_skins": vrai_faces.list_skins(),
            "programs": library.list_programs(),
            "modules": library.list_modules(),
            "samples": library.list_sample_scenarios(),
            "v1_scenarios": v1_scens,
            "has_api_key": bool(vault.get("ANTHROPIC_API_KEY")),
            "active_session": active,
            "base_url": _base_url_for_qr(request),
            "lan_ip": _lan_ip(),
            "ehrs": ehr_registry.REGISTRY,         # V3 — wizard step 2b
            "default_ehr": ehr_registry.default_id(),
            # V7 M12 — Activity catalog for the room-mode Step 4r picker.
            # Each row in the room-mode editor can pre-fill from one
            # of these activities; the JS sends activity_id along with
            # the row in the /api/room/start payload.
            "activities_for_room": ehr_db.list_activities(),
        },
    )


@app.post("/portal/control/start")
async def control_start(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    api_key = vault.get("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"ok": False, "message": "Anthropic API key required."})
    # M38 — Seed the process-wide cache so station-turn routes prefer
    # the *current* vault key over the encounter's snapshot.
    _capture_anthropic_key(api_key)
    form = await request.form()
    scenario_name = (form.get("scenario_name") or "").strip()
    if not scenario_name:
        return JSONResponse({"ok": False, "message": "Scenario name required."})
    program_id = (form.get("program_id") or "").strip() or None
    week_raw = (form.get("week") or "").strip()
    week = int(week_raw) if week_raw.isdigit() else None
    selected_modules = [m for m in form.getlist("modules") if m]
    selected_personas = [p for p in form.getlist("personas") if p]
    if not selected_personas:
        return JSONResponse({"ok": False, "message": "At least one persona must be selected."})
    # V8 — personas the instructor opted to give an avatar (only those also selected).
    _sel = set(selected_personas)
    avatar_personas = [p for p in form.getlist("avatar_personas") if p in _sel]
    ehr_id = (form.get("ehr_id") or ehr_registry.default_id()).strip()
    if ehr_registry.get(ehr_id) is None:
        ehr_id = ehr_registry.default_id()
    # V4 — capture the ElevenLabs key (vault → env → keyfile) so station
    # routes, which have no operator cookie, can still synthesize voices.
    el_key = voices.get_api_key(vault)
    sess = control_session.create_session(
        scenario_name=scenario_name,
        api_key=api_key,
        scenario_notes=(form.get("scenario_notes") or "").strip(),
        program_id=program_id,
        week=week,
        selected_modules=selected_modules,
        scenario_text=(form.get("scenario_text") or "").strip(),
        selected_personas=selected_personas,
        avatar_personas=avatar_personas,
        ehr_id=ehr_id,
        elevenlabs_api_key=el_key,
    )
    # Build + persist the ChartSeed eagerly so the EHR bundle bootstraps fast.
    _ensure_ehr_session_registered(sess)
    # FR-011 G1 — snapshot the freshly-configured session NOW, so even an
    # ungraceful kill (which skips the shutdown hook) resumes the scenario the
    # instructor just built instead of dropping them at a fresh Setup wizard.
    try:
        from . import session_state
        session_state.clear_last_resume()   # G7 — a fresh launch isn't a resume
        session_state.persist()
    except Exception:  # noqa: BLE001 — resumability must never block configure
        pass
    return JSONResponse({
        "ok": True,
        "session_id": sess.id,
        "join_code": sess.join_code,
        "redirect_url": "/portal/control/ops",
    })


@app.post("/portal/control/end")
async def control_end(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """End the active session — auto-save a debrief JSON before clearing
    so the instructor can review it afterward."""
    sess = control_session.get_active()
    saved_id = None
    if sess is not None:
        try:
            db = debrief_mod.build(sess)
            path = debrief_mod.save(db)
            saved_id = sess.id
        except Exception:  # noqa: BLE001 — debrief save must not block ending
            saved_id = None
    # V6 — broadcast 'ended' to every device before tearing down the
    # active session, so each one freezes its UI and stops audio loops.
    from .devices.ws import manager as _device_ws_manager
    await _device_ws_manager.broadcast_state("ended")
    control_session.end_active()
    if saved_id:
        return RedirectResponse(f"/portal/debrief/{saved_id}", status_code=303)
    return RedirectResponse("/portal/debrief", status_code=303)


async def _control_stage_page(
    request: Request,
    join: str | None,
    patient_persona_id: str | None,
    embed: int | None,
    stage: str,
):
    """M42 — Multi-patient-aware ops view. FR-005: ONE template, TWO stages —
    `/portal/control/setup` (stage="setup": pre-start configuration — devices,
    medication board, skins/voices — ending in ▶ Start scenario) and
    `/portal/control/ops` (stage="live": running the encounter — transcript, PTT,
    say-as-character, device ops). Sections show/hide by stage; element ids stay in
    the DOM either way so every existing card script keeps working unchanged.

    Query params:
      - `join` — when set, looks up the session/encounter by join code
        instead of relying on `control_session.get_active()`. The
        v6-compat singleton path returns None in v7 multi-encounter
        rooms; this param makes the device manager usable in room mode.
      - `patient_persona_id` — when set, the device-add modal will
        default the patient assignment to this persona (instead of
        "— unassigned —"). The encounter console passes this so a
        device added from a bed's manager auto-assigns to that bed's
        primary patient.
      - `embed=1` — when set, the ops-view top header is hidden
        (so when embedded in the encounter console's modal, the
        operator doesn't see two stacked headers).
    """
    sess: control_session.ControlSession | None = None
    if join:
        sess = control_session.get_by_join_code(join)
    if sess is None:
        sess = control_session.get_active()
    if sess is None:
        return RedirectResponse("/portal/control", status_code=303)
    # FR-005 stage routing: a freshly-configured session lands on Setup; once
    # running, the ops URL is the live page. (Setup stays reachable while
    # running — for level-2 mid-scenario changes — via its own URL.)
    if stage == "live" and not embed and getattr(sess, "state", "") == "configured":
        q = f"?join={join}" if join else ""
        return RedirectResponse(f"/portal/control/setup{q}", status_code=303)
    # Hydrate personas with their resolved voice profile so the operator's
    # PTT panel can speak the response in the right voice without a second fetch.
    personas_in_use = []
    avatar_set = set(sess.avatar_personas or [])
    for pid in sess.selected_personas:
        p = library.get_persona(pid)
        if p:
            personas_in_use.append({
                **p,
                "voice_profile": library.voice_profile_for(p),
                # V8 — instructor opted this persona in for a VRAI Faces avatar;
                # the ops view shows its tablet-pairing QR (assign-for-use).
                "avatar_enabled": pid in avatar_set,
                # V8 — currently-assigned skin id so the ops device cell's skin
                # picker can highlight it (and show "none" when unassigned).
                "avatar_skin": vrai_faces.assigned_skin_id(pid),
            })
    modules_in_use = []
    for mid in sess.selected_modules:
        m = library.get_module(mid)
        if m:
            modules_in_use.append(m)
    # M42 — Pre-fill the add-device patient dropdown via a bootstrap-
    # JSON field the client reads. Falls back to the session's primary
    # patient persona when the caller didn't pass one explicitly.
    default_device_patient = (
        patient_persona_id
        or ehr_seed.patient_persona_id(sess)   # role-aware (not blindly [0] → the doctor)
        or ""
    )
    # This page shows the per-character device QRs — make sure the avatar app is
    # up + LAN-reachable so a scanned tablet doesn't hit connection-refused.
    _ensure_vrai_app_for_qr(request)
    return templates.TemplateResponse(
        request, "control_ops.html",
        {
            "active": "control",
            "session": sess,
            "personas_in_use": personas_in_use,
            "modules_in_use": modules_in_use,
            # V8 — skin library for the on-the-fly per-character skin picker in
            # the device QR cells (assign/change a face mid-encounter).
            "avatar_skins": vrai_faces.list_skins(),
            "base_url": _base_url_for_qr(request),
            "lan_ip": _lan_ip(),
            "default_device_patient_id": default_device_patient,
            "embed_mode": bool(embed),
            "stage": stage,
            # FR-005: personas not yet in the session — the Setup page's
            # "+ Add character" picker (e.g. add the pharmacist mid-stream).
            "addable_personas": [
                p for p in library.list_personas()
                if str(p.get("id") or "") not in set(sess.selected_personas)
            ],
        },
    )


@app.get("/portal/control/ops", response_class=HTMLResponse)
async def control_ops(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    join: str | None = None,
    patient_persona_id: str | None = None,
    embed: int | None = None,
):
    """FR-005 — Live Operations (stage 2): running the encounter."""
    return await _control_stage_page(request, join, patient_persona_id, embed, "live")


@app.get("/portal/control/setup", response_class=HTMLResponse)
async def control_setup(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    join: str | None = None,
    patient_persona_id: str | None = None,
):
    """FR-005 — Scenario Setup (stage 1): devices, medications, skins/voices →
    ▶ Start scenario (opens Live Operations in a new window)."""
    return await _control_stage_page(request, join, patient_persona_id, None, "setup")


@app.get("/portal/control/errors")
async def control_errors_builder(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-008 S5 — the staged-error BUILDER (own page, reached from Setup): a
    six-step structured wizard (type → vector → encounter → grounded payload →
    optional impact → review-and-arm). Bounded by construction — every choice
    comes from the catalog ∩ the session's chart; free text is the debrief note
    only. Armed errors are managed from the Live window's status card.

    FR-008 S7 — ``?bed=<encounter_id>`` scopes the whole builder to one bed in a
    multi-patient room (the page threads it onto every API call); absent, it
    targets the single active session."""
    bed = (request.query_params.get("bed") or "").strip()
    bed_label = ""
    if bed:
        room = control_room.get_active_room()
        enc = room.encounters.get(bed) if room else None
        if enc is not None:
            bed_label = getattr(enc, "encounter_label", "") or enc.scenario_name or ""
    return templates.TemplateResponse(
        request, "control_errors.html", {"bed": bed, "bed_label": bed_label})


@app.get("/api/control/state")
async def api_control_state(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"active": False})
    stations_payload = []
    for s in sess.stations.values():
        persona = library.get_persona(s.persona_id) if s.persona_id else None
        ua = s.user_agent.lower()
        platform = (
            "iPhone" if "iphone" in ua else
            "iPad" if "ipad" in ua else
            "Android" if "android" in ua else
            "Mac" if "macintosh" in ua else
            "Windows" if "windows" in ua else
            "Other"
        )
        stations_payload.append({
            "station_id": s.station_id,
            "persona_id": s.persona_id,
            "persona_name": (persona or {}).get("name", "—") if persona else None,
            "persona_role": (persona or {}).get("role", "") if persona else "",
            "altered_state": (persona or {}).get("alteredState") if persona else None,
            "safety_class": (persona or {}).get("safetyClass", "baseline") if persona else "baseline",
            "platform": platform,
            "online": s.online,
            "turns": len(s.history),
            "seconds_since_seen": int(time.time() - s.last_seen),
        })
    return JSONResponse({
        "active": True,
        "scenario_name": sess.scenario_name,
        "join_code": sess.join_code,
        "state": sess.state,
        "stations": stations_payload,
    })


@app.get("/api/control/seed_report")
async def api_control_seed_report(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """V6 — return the active session's chart seed_report so the operator
    UI can show validator warnings (allergy collisions, biographic drift,
    catalog misses) and auto-corrections inline."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"active": False})
    seed = ehr_db.seed(sess.id) or {}
    return JSONResponse({
        "active":    True,
        "condition": seed.get("condition"),
        "report":    seed.get("seed_report") or {},
    })


@app.get("/api/control/seed/medications")
async def api_control_seed_meds(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """V6.1 — list every med the seeder put on the MAR, with each row's
    `included` flag (defaults to true if missing). Operator UI uses this
    to render the per-med check-list before students join."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"active": False, "medications": []})
    seed = ehr_db.seed(sess.id) or {}
    meds = []
    for m in (seed.get("medications") or []):
        if not isinstance(m, dict):
            continue
        meds.append({
            "med_id":     m.get("med_id") or m.get("name"),
            "name":       m.get("name"),
            "dose":       m.get("dose"),
            "route":      m.get("route"),
            "frequency":  m.get("frequency"),
            "drug_class": m.get("drug_class"),
            "high_alert": bool(m.get("high_alert")),
            "rationale":  m.get("rationale"),
            "current_status": m.get("current_status"),
            "included":   m.get("included", True),
        })
    return JSONResponse({"active": True, "medications": meds})


@app.post("/api/control/seed/medications/toggle")
async def api_control_seed_meds_toggle(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """V6.1 — toggle a med's `included` flag in the seed. POST body:
    {"med_id": "...", "included": bool}. Persists back to ehr_db so the
    next EHR bootstrap (and the chart fold) sees the new shape. Students
    who already loaded the EHR will see the change on their next chart
    poll (5s)."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"ok": False, "error": "No active session"}, status_code=409)
    body = await request.json()
    med_id   = (body.get("med_id") or "").strip()
    included = bool(body.get("included"))
    if not med_id:
        raise HTTPException(400, "Missing 'med_id'.")
    seed = ehr_db.seed(sess.id) or {}
    meds = seed.get("medications") or []
    found = False
    for m in meds:
        if isinstance(m, dict) and (m.get("med_id") == med_id or m.get("name") == med_id):
            m["included"] = included
            found = True
            break
    if not found:
        raise HTTPException(404, f"med_id {med_id!r} not on this MAR")
    seed["medications"] = meds
    ehr_db.update_seed(sess.id, seed)
    return JSONResponse({"ok": True, "med_id": med_id, "included": included})


@app.post("/api/control/personas/add")
async def api_control_add_persona(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-005 — add a library persona (e.g. the pharmacist) to the ACTIVE session
    without relaunching. Selection only gates UI surfaces (PTT chips, QR cells,
    say-as picker); the speak/listen plumbing already works for any persona."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"ok": False, "error": "no running scenario"},
                            status_code=409)
    body = await request.json()
    pid = str((body or {}).get("persona_id") or "").strip()
    persona = library.get_persona(pid)
    if persona is None:
        return JSONResponse({"ok": False, "error": "unknown persona"},
                            status_code=404)
    if pid not in sess.selected_personas:
        sess.selected_personas.append(pid)
    if bool((body or {}).get("avatar")) and pid not in (sess.avatar_personas or []):
        sess.avatar_personas.append(pid)
    return JSONResponse({"ok": True, "persona_id": pid,
                         "name": persona.get("name") or pid})


@app.post("/api/control/personas/avatar")
async def api_control_persona_avatar(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-006 — flip a session character between 🪞 Avatar (3D face tablet) and
    🔊 Audio-only (flat portrait + voice; low-cost tablets, no WebGPU). The choice
    drives the label AND the minted QR (`mode=audio`)."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"ok": False, "error": "no running scenario"},
                            status_code=409)
    body = await request.json()
    pid = str((body or {}).get("persona_id") or "").strip()
    if pid not in sess.selected_personas:
        return JSONResponse({"ok": False, "error": "persona not in session"},
                            status_code=404)
    want = bool((body or {}).get("avatar"))
    have = pid in (sess.avatar_personas or [])
    if want and not have:
        sess.avatar_personas.append(pid)
    elif not want and have:
        sess.avatar_personas.remove(pid)
    return JSONResponse({"ok": True, "persona_id": pid, "avatar": want})


@app.post("/api/control/personas/skin")
async def api_control_persona_skin(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 — assign (or clear) a character's portrait/skin from the wizard's
    image picker. Global per-persona, so it works before launch: the chosen image
    becomes the flat audio portrait AND the 3D rig's source photo (both read by
    the face page via vrai_faces.resolve_portrait). Empty skin_id clears it."""
    body = await request.json()
    pid = str((body or {}).get("persona_id") or "").strip()
    skin_id = str((body or {}).get("skin_id") or "").strip()
    if not pid:
        return JSONResponse({"ok": False, "error": "persona_id required"},
                            status_code=400)
    if skin_id:
        ok = vrai_faces.assign_skin(skin_id, pid)
    else:
        vrai_faces.clear_portrait(pid)
        ok = True
    return JSONResponse({"ok": bool(ok), "persona_id": pid, "skin_id": skin_id})


@app.post("/api/control/state")
async def api_control_set_state(
    state: Annotated[str, Form()],
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    if state not in {"configured", "running", "paused", "ended"}:
        raise HTTPException(400, "Invalid state")
    control_session.set_state(state)
    # V6 — broadcast the state flip to every connected device. Pause halts
    # looping alarm audio + disables student input on the device; resume
    # re-folds and re-enables. End triggers the same client behaviour as
    # pause but with a terminal banner.
    from .devices.ws import manager as _device_ws_manager
    await _device_ws_manager.broadcast_state(state)
    return JSONResponse({"ok": True, "state": state})


@app.get("/api/control/transcript")
async def api_control_transcript(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    since: int = 0,
    since_ts: float = 0.0,
):
    """Return transcript entries from index `since` onward. The ops view
    polls this every 2s and renders new entries — cheap because we only
    send the delta.

    V6: also returns the device event delta (programming, alarms,
    silence, clear) since `since_ts` so the operator's transcript card
    can interleave them chronologically with chat turns. Device-event
    indices use timestamps (not list positions) because the device
    event log can be appended-to from many WebSocket connections in
    parallel — timestamps are the natural cursor.
    """
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"active": False, "entries": [], "total": 0,
                              "device_events": [], "device_since_ts": 0.0})
    entries = sess.transcript[since:]
    # V6 — pull device events from SQLite, filter to those after since_ts.
    # V6.1 — skip internal engine ticks (pump.tick / feed.tick) — they
    # fire constantly and aren't operator-readable; the human-meaningful
    # action (device.time_advanced) is logged separately.
    device_rows: list[dict[str, Any]] = []
    max_ts = float(since_ts or 0)
    _NOISE_EVENT_TYPES = {"pump.tick", "feed.tick"}
    try:
        for ev in ehr_db.device_events(session_id=sess.id):
            if ev["ts"] <= since_ts:
                continue
            if ev["type"] in _NOISE_EVENT_TYPES:
                # Still advance the cursor so the next poll skips them.
                if ev["ts"] > max_ts:
                    max_ts = ev["ts"]
                continue
            station = sess.device_stations.get(ev["station_id"]) if sess.device_stations else None
            payload = ev.get("payload") or {}
            device_rows.append({
                "ts":           ev["ts"],
                "id":           ev.get("id"),
                "station_id":   ev["station_id"],
                "station_label":(station.label if station else "") or ev["station_id"],
                "device_model": (station.device_model if station else ""),
                "type":         ev["type"],
                "surface":      ev.get("surface"),
                "payload":      payload,
                "summary":      _summarize_device_event(ev["type"], payload),
            })
            if ev["ts"] > max_ts:
                max_ts = ev["ts"]
    except Exception:
        pass
    return JSONResponse({
        "active": True,
        "total": len(sess.transcript),
        "entries": [
            {
                "ts": e.ts,
                "source": e.source,
                "source_label": e.source_label,
                "persona_id": e.persona_id,
                "persona_name": e.persona_name,
                "direction": e.direction,
                "text": e.text,
                "latency_ms": e.latency_ms,
            }
            for e in entries
        ],
        "device_events":  device_rows,
        "device_since_ts": max_ts,
    })


def _summarize_device_event(type_: str, payload: dict) -> str:
    """One-line operator-readable summary of a device event."""
    p = payload or {}
    if type_ == "pump.program":
        ch    = p.get("channel") or ""
        rate  = p.get("rate_ml_hr")
        vtbi  = p.get("vtbi_ml")
        drug  = p.get("drug_label") or p.get("drug_code") or "—"
        over  = " (soft-override)" if p.get("soft_override") else ""
        return (f"Programmed{' Ch ' + ch if ch else ''}: {drug} · "
                f"rate {rate} mL/hr · VTBI {vtbi} mL{over}")
    if type_ == "feed.program":
        return (f"Programmed: {p.get('mode') or '—'} · rate {p.get('rate_ml_hr')} mL/hr · "
                f"vol {p.get('volume_ml')} mL")
    if type_ == "pump.start":
        return f"Started{' Ch ' + (p.get('channel') or '')}"
    if type_ == "pump.pause":
        return f"Paused{' Ch ' + (p.get('channel') or '')}"
    if type_ == "pump.stop":
        return f"Stopped{' Ch ' + (p.get('channel') or '')}"
    if type_ == "pump.rate_change":
        return (f"Rate change{' Ch ' + (p.get('channel') or '')}: {p.get('rate_ml_hr')} mL/hr"
                + (" (soft-override)" if p.get("soft_override") else ""))
    if type_ == "feed.start":  return "Feed started"
    if type_ == "feed.pause":  return "Feed paused"
    if type_ == "feed.stop":   return "Feed stopped"
    if type_ == "pump.power":  return f"Power {p.get('state', '—').upper()}"
    if type_ == "feed.power":  return f"Power {p.get('state', '—').upper()}"
    if type_ == "alarm.injected":
        auto = " (auto)" if p.get("auto") else ""
        return f"ALARM: {p.get('tone', '—')}{auto}"
    if type_ == "alarm.silenced":
        return f"silenced: {p.get('tone', '—')}"
    if type_ == "alarm.cleared":
        return f"cleared: {p.get('tone', '—')}"
    if type_ == "device.assigned":
        return f"reassigned to {p.get('character_id') or '— unassigned —'}"
    if type_ == "device.time_advanced":
        mins = p.get("minutes", 0)
        try:
            mins = float(mins)
        except (TypeError, ValueError):
            mins = 0
        if mins >= 60 and mins == int(mins):
            return f"⏩ Time advanced +{int(mins // 60)} hr" + (f" {int(mins % 60)} min" if mins % 60 else "")
        return f"⏩ Time advanced +{mins:g} min"
    if type_ == "cabinet.administer":
        # V6.1.6 — the quick-checkoff path on med carts. Operators want
        # to see "RN administered <med> <dose> <route> to <Patient>" in
        # the live transcript, not just an opaque event type.
        who   = p.get("character_name") or p.get("character_id") or "?"
        med   = p.get("med_name") or "med"
        dose  = p.get("dose") or ""
        route = p.get("route") or ""
        scan  = " (scanned)" if p.get("scan_used") else " (no scan)"
        by    = p.get("administered_by") or "RN"
        return f"💊 {by} administered {med}{' ' + dose if dose else ''}{' ' + route if route else ''} to {who}{scan}"
    if type_.startswith("cabinet."):
        verb = type_.split(".", 1)[-1]
        return f"Cabinet {verb}: {p.get('med_id') or p.get('verb') or ''}".strip()
    return type_


@app.post("/api/control/operator/turn")
async def api_control_operator_turn(
    persona_id: Annotated[str, Form()],
    message: Annotated[str, Form()],
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Operator-side PTT — the instructor engages a character directly from
    the control room. One persona per turn. Routed through the same runtime
    as a station turn; transcript records source='operator'."""
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"ok": False, "error": "No active session."}, status_code=400)
    if persona_id not in sess.selected_personas:
        return JSONResponse({"ok": False, "error": f"Persona {persona_id} is not in this session."}, status_code=400)
    if not message.strip():
        return JSONResponse({"ok": False, "error": "Empty message."}, status_code=400)
    persona = library.get_persona(persona_id)
    if persona is None:
        return JSONResponse({"ok": False, "error": f"Unknown persona {persona_id}."}, status_code=400)
    char = library.persona_as_character(persona)
    scenario = {
        "id": sess.id,
        "name": sess.scenario_name,
        "patient": {"history": sess.scenario_text} if sess.scenario_text else {},
    }
    # FR-009 — inject the shift-handoff prompt block (+ med board / staged errors) so
    # the chosen counterpart RUNS the handoff when engaged via operator PTT. No-op for
    # any non-counterpart character (matched by card id).
    # FR-013 P4 — local-practice overlay (program-wide toggle) rides the same
    # channel, so an operator-engaged character also "speaks local". No-op when
    # the overlay is off or no items are active.
    from portal import handoff as _ho, local_context as _lc, med_errors as _me, med_orders as _mo
    _ctx = "\n\n".join(x for x in (
        _mo.prompt_block_for(sess.id, char),
        _me.prompt_block_for(sess.id, char),
        _ho.prompt_block_for(sess.id, char),
        _lc.overlay_block(),
    ) if x)
    turn_card = {**char, "_extra_context": _ctx} if _ctx else char
    import time as _time
    # V6 — prefer the *current* vault key, falling back to the session-
    # cached key only if the vault doesn't have one. This lets the operator
    # update an invalid / rotated Anthropic key at /portal/credentials and
    # have the change take effect immediately on the next PTT — no need to
    # end and relaunch the scenario.
    live_key = vault.get("ANTHROPIC_API_KEY") or sess.api_key
    sess.api_key = live_key   # keep the session in sync so other routes benefit
    sim_sess = runtime.create_session_from_data(
        scenario=scenario,
        characters={persona_id: turn_card},
        api_key=live_key,
    )
    turn_start = _time.time()
    result = runtime.take_turn(sim_sess.id, persona_id, message)
    latency_ms = int((_time.time() - turn_start) * 1000)
    runtime.end_session(sim_sess.id)
    if result.get("ok"):
        sess.log_turn(
            source="operator",
            source_label="Operator (control room)",
            persona_id=persona_id,
            persona_name=persona.get("name", persona_id),
            student_text=message,
            character_text=result["reply"],
            latency_ms=latency_ms,
        )
        result["latency_ms"] = latency_ms
    return JSONResponse(result)


@app.post("/api/room/encounter/{encounter_id}/operator/turn")
async def api_room_encounter_operator_turn(
    encounter_id: str,
    persona_id: Annotated[str, Form()],
    message: Annotated[str, Form()],
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Operator PTT scoped to ONE bed in a multi-patient room — the instructor
    engages a character on this encounter from the new console (parity with the
    classic control room's operator PTT). Mirrors /api/control/operator/turn but
    resolves the encounter (get_active() is None in a room) and uses the cache-
    first key (room encounters carry no stamped api_key)."""
    from portal import control_room as _cr
    room = _cr.get_active_room()
    enc = room.encounters.get(encounter_id) if room else None
    if enc is None:
        return JSONResponse({"ok": False, "error": "Unknown encounter."}, status_code=404)
    if persona_id not in enc.selected_personas:
        return JSONResponse({"ok": False, "error": f"Persona {persona_id} is not on this bed."},
                            status_code=400)
    if not message.strip():
        return JSONResponse({"ok": False, "error": "Empty message."}, status_code=400)
    persona = library.get_persona(persona_id)
    if persona is None:
        return JSONResponse({"ok": False, "error": f"Unknown persona {persona_id}."}, status_code=400)
    char = library.persona_as_character(persona)
    scenario = {
        "id": enc.id,
        "name": enc.scenario_name,
        "patient": {"history": enc.scenario_text} if enc.scenario_text else {},
    }
    # FR-009 — inject the shift-handoff prompt block (+ med board / staged errors) so
    # the chosen counterpart actually RUNS the handoff when the operator engages it
    # here. Keyed by enc.id (the handoff/med/error state's session id under
    # ?bed=<encounter_id>); prompt_block_for is a no-op for any non-counterpart.
    from portal import handoff as _ho, local_context as _lc, med_errors as _me, med_orders as _mo
    _ctx = "\n\n".join(x for x in (
        _mo.prompt_block_for(enc.id, char),
        _me.prompt_block_for(enc.id, char),
        _ho.prompt_block_for(enc.id, char),
        _lc.overlay_block(),                  # FR-013 P4 — local-practice overlay
    ) if x)
    turn_card = {**char, "_extra_context": _ctx} if _ctx else char
    import time as _time
    live_key = _resolve_anthropic_key(enc) or (vault.get("ANTHROPIC_API_KEY") or "")
    sim_sess = runtime.create_session_from_data(
        scenario=scenario, characters={persona_id: turn_card}, api_key=live_key)
    turn_start = _time.time()
    result = runtime.take_turn(sim_sess.id, persona_id, message)
    latency_ms = int((_time.time() - turn_start) * 1000)
    runtime.end_session(sim_sess.id)
    if result.get("ok"):
        enc.log_turn(
            source="operator", source_label="Operator (encounter console)",
            persona_id=persona_id, persona_name=persona.get("name", persona_id),
            student_text=message, character_text=result["reply"], latency_ms=latency_ms)
        result["latency_ms"] = latency_ms
    return JSONResponse(result)


# ----- Station (mobile) flow ---------------------------------------------

@app.get("/join", response_class=HTMLResponse)
async def join_landing(request: Request, code: str | None = None):
    """Public landing page. Mobile scans QR → lands here. No auth — the
    join_code itself is the access token for stations."""
    return templates.TemplateResponse(
        request, "join.html",
        {"code": (code or "").upper()},
    )


@app.get("/api/join/{code}/personas")
async def api_join_personas(code: str):
    """Public persona list for the join page — the join code is the access token
    (no operator auth, same trust as /join). Returns the personas a student can
    join AS for this session/bed (the encounter's selected_personas), resolved
    to {id, name, role, roleGroup} for the dropdown. The previous client used
    the operator-only /api/personas, which 401s for a public student and left
    the dropdown empty."""
    sess = control_session.get_by_join_code(code)
    if sess is None:
        return JSONResponse({"ok": False, "personas": []}, status_code=404)
    out: list[dict[str, Any]] = []
    for pid in sess.selected_personas:
        p = library.get_persona(pid)
        if p:
            out.append({
                "id": pid,
                "name": p.get("name") or pid,
                "role": p.get("role") or "",
                "roleGroup": p.get("roleGroup") or "Personas",
            })
    return JSONResponse({"ok": True, "personas": out})


@app.post("/join")
async def join_submit(
    request: Request,
    code: Annotated[str, Form()],
    persona_id: Annotated[str, Form()],
):
    sess = control_session.get_by_join_code(code)
    if sess is None:
        return RedirectResponse(f"/join?code={code}&error=notfound", status_code=303)
    if persona_id not in sess.selected_personas:
        return RedirectResponse(f"/join?code={code}&error=persona", status_code=303)
    user_agent = request.headers.get("user-agent", "")[:200]
    import secrets as _secrets
    station_id = _secrets.token_urlsafe(8)
    st = sess.add_station(station_id, user_agent=user_agent)
    st.persona_id = persona_id
    return RedirectResponse(f"/station/{sess.join_code}/{station_id}", status_code=303)


@app.get("/station/{join_code}/{station_id}", response_class=HTMLResponse)
async def station_page(
    join_code: str,
    station_id: str,
    request: Request,
):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or station_id not in sess.stations:
        return RedirectResponse(f"/join?code={join_code}&error=notfound", status_code=303)
    station = sess.stations[station_id]
    persona = library.get_persona(station.persona_id) if station.persona_id else None
    if persona is None:
        return RedirectResponse(f"/join?code={join_code}", status_code=303)
    voice_profile = library.voice_profile_for(persona)
    # FR-016 — intercom needs the room bus + this bed's identity. The session
    # IS the encounter (room.encounters is keyed by session id); room_code is
    # the active room's code when this session belongs to it.
    _room = control_room.get_active_room()
    _room_code = (_room.room_code if (_room and sess.id in _room.encounters) else "")
    return templates.TemplateResponse(
        request, "station.html",
        {
            "session": sess,
            "station": station,
            "persona": persona,
            "voice_profile": voice_profile,
            # V4 — the instructor's ElevenLabs voice assignment for this
            # persona ("" → station uses the browser voice).
            "voice_id": sess.voice_assignments.get(persona["id"], ""),
            "history": station.history,
            # FR-016 — intercom bus + bed identity (empty room_code → single
            # session not in a room; the intercom UI stays hidden).
            "room_code": _room_code,
            "encounter_id": sess.id,
            "bed_label": getattr(sess, "scenario_name", "") or persona.get("name", "Bedside"),
        },
    )


@app.post("/api/station/{join_code}/{station_id}/turn")
async def api_station_turn(
    join_code: str,
    station_id: str,
    message: Annotated[str, Form()],
):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or station_id not in sess.stations:
        return JSONResponse({"ok": False, "error": "Station not found."}, status_code=404)
    station = sess.stations[station_id]
    station.touch()
    persona = library.get_persona(station.persona_id) if station.persona_id else None
    if persona is None:
        return JSONResponse({"ok": False, "error": "No persona assigned."}, status_code=400)
    # Build an ad-hoc runtime session per station turn (lightweight; uses
    # station.history as the rolling context).
    char = library.persona_as_character(persona)
    scenario = {
        "id": sess.id,
        "name": sess.scenario_name,
        "patient": {"history": sess.scenario_text} if sess.scenario_text else {},
        "curriculum": {"touchpoints": []},
    }
    # M38 — Prefer the process-wide Anthropic-key cache over the
    # snapshot stamped on the encounter at room start. The cache is
    # refreshed every time an operator route reads the vault, so a
    # /portal/credentials update propagates without restarting the
    # room. Also keep sess.api_key in sync so other paths benefit.
    live_key = _resolve_anthropic_key(sess)
    if live_key and live_key != sess.api_key:
        sess.api_key = live_key
    if not live_key:
        return JSONResponse(
            {"ok": False,
             "error": "No Anthropic API key configured. Open "
                      "/portal/credentials to add it, then try again — "
                      "the change applies immediately, no restart needed."},
            status_code=200,
        )
    # Reuse runtime by creating a transient session per turn — simpler than
    # caching a SimSession alongside ControlSession.
    from portal import local_context as _lc
    _ov = _lc.overlay_block()        # FR-013 P4 — local-practice overlay (audio station)
    sim_sess = runtime.create_session_from_data(
        scenario=scenario,
        characters={persona["id"]: ({**char, "_extra_context": _ov} if _ov else char)},
        api_key=live_key,
    )
    # Replay station history into the sim session so context is preserved
    import time as _time
    for h in station.history[-runtime.HISTORY_WINDOW:]:
        sim_sess.history.append(runtime.TurnRecord(
            addressee=persona["id"],
            student_utterance=h.get("user", ""),
            character_response=h.get("character", ""),
            timestamp=h.get("ts", _time.time()),
        ))
    turn_start = _time.time()
    # M38 — Translate Anthropic 401 (invalid x-api-key) into a friendly
    # chat message that tells the operator exactly where to fix it,
    # instead of dumping a raw repr into the chat bubble.
    try:
        result = runtime.take_turn(sim_sess.id, persona["id"], message)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        runtime.end_session(sim_sess.id)
        if "401" in msg or "invalid x-api-key" in msg.lower() \
                or "authentication" in msg.lower():
            return JSONResponse(
                {"ok": False,
                 "error": "Anthropic rejected the API key (401). Update "
                          "ANTHROPIC_API_KEY at /portal/credentials and "
                          "try again — the new key applies immediately."},
                status_code=200,
            )
        return JSONResponse({"ok": False,
                              "error": f"Turn failed: {msg}"},
                             status_code=200)
    latency_ms = int((_time.time() - turn_start) * 1000)
    # Clean up the transient sim session
    runtime.end_session(sim_sess.id)
    # M38 — runtime.take_turn returns {"ok": False, "error": …} on
    # caught failures. Also translate those.
    if not result.get("ok"):
        err = (result.get("error") or "").lower()
        if "401" in err or "invalid x-api-key" in err or "authentication" in err:
            result = {
                "ok": False,
                "error": "Anthropic rejected the API key (401). Update "
                         "ANTHROPIC_API_KEY at /portal/credentials and "
                         "try again — the new key applies immediately.",
            }
    if result.get("ok"):
        station.history.append({
            "user": message,
            "character": result["reply"],
            "character_name": result["character_name"],
            "ts": _time.time(),
        })
        sess.log_turn(
            source=f"station:{station_id}",
            source_label=f"{persona.get('name','—')} station",
            persona_id=persona["id"],
            persona_name=persona.get("name", persona["id"]),
            student_text=message,
            character_text=result["reply"],
            latency_ms=latency_ms,
        )
    return JSONResponse(result)


# ── FR-007 v2 — shared "one tablet, many patients" character station ──────────
def _room_shared_scenario(room) -> dict[str, Any]:
    """A room-level scenario: the shared character sees EVERY bed's patient, so it
    answers as ONE instance spanning the room (not a per-bed context)."""
    rps: list[dict[str, Any]] = []
    for e in room.encounters.values():
        pp = library.get_persona(e.patient_persona_id) if e.patient_persona_id else None
        rps.append({
            "label": e.encounter_label or e.scenario_name or (pp.get("name") if pp else "patient"),
            "name": (pp.get("name") if pp else ""),
            "history": e.scenario_text or "",
        })
    return {"id": room.room_id, "name": room.label or "Shared care room",
            "patient": {}, "room_patients": rps, "curriculum": {"touchpoints": []}}


@app.get("/portal/room/shared/{persona_id}", response_class=HTMLResponse)
async def portal_room_shared_station(request: Request, persona_id: str):
    """The shared character's chat surface — reachable on the LAN (a tablet), like a
    device station; one instance covering the whole room."""
    room = control_room.get_active_room()
    if room is None or persona_id not in (room.shared_personas or []):
        raise HTTPException(404, "No such shared character in the active room.")
    persona = library.get_persona(persona_id) or {}
    patients = [(e.encounter_label or e.scenario_name or "Bed")
                for e in room.encounters.values()]
    return templates.TemplateResponse(request, "shared_station.html", {
        "persona_id": persona_id,
        "persona_name": persona.get("name") or persona_id,
        "persona_role": persona.get("role") or "",
        "room_label": room.label or "Room",
        "patients": patients,
    })


@app.post("/api/room/shared/{persona_id}/turn")
async def api_room_shared_turn(persona_id: str, message: Annotated[str, Form()]):
    room = control_room.get_active_room()
    if room is None:
        return JSONResponse({"ok": False, "error": "No active room."}, status_code=404)
    if persona_id not in (room.shared_personas or []):
        return JSONResponse({"ok": False, "error": "Not a shared character."}, status_code=404)
    persona = library.get_persona(persona_id)
    if persona is None:
        return JSONResponse({"ok": False, "error": "Unknown persona."}, status_code=400)
    station = room.shared_station(persona_id)
    station.touch()
    encs = list(room.encounters.values())
    live_key = _resolve_anthropic_key(encs[0]) if encs else None
    if not live_key:
        return JSONResponse({"ok": False, "error": "No Anthropic API key configured. "
                             "Open /portal/credentials to add it, then try again."},
                            status_code=200)
    char = library.persona_as_character(persona)
    scenario = _room_shared_scenario(room)
    from portal import local_context as _lc
    _ov = _lc.overlay_block()        # FR-013 P4 — local-practice overlay (shared station)
    sim_sess = runtime.create_session_from_data(
        scenario=scenario,
        characters={persona["id"]: ({**char, "_extra_context": _ov} if _ov else char)},
        api_key=live_key)
    import time as _time
    for h in station.history[-runtime.HISTORY_WINDOW:]:
        sim_sess.history.append(runtime.TurnRecord(
            addressee=persona["id"], student_utterance=h.get("user", ""),
            character_response=h.get("character", ""), timestamp=h.get("ts", _time.time())))
    try:
        result = runtime.take_turn(sim_sess.id, persona["id"], message)
    except Exception as exc:  # noqa: BLE001
        runtime.end_session(sim_sess.id)
        return JSONResponse({"ok": False, "error": f"Turn failed: {exc}"}, status_code=200)
    runtime.end_session(sim_sess.id)
    if result.get("ok"):
        station.history.append({
            "user": message, "character": result["reply"],
            "character_name": result.get("character_name", persona.get("name", "")),
            "ts": _time.time(),
        })
        # Voice for the shared station's push-to-talk TTS — the shared character's
        # ElevenLabs voice, assigned once on any bed. Empty -> the station falls back
        # to the browser voice.
        for e in encs:
            v = (getattr(e, "voice_assignments", {}) or {}).get(persona_id)
            if v:
                result["voice_id"] = v
                break
    return JSONResponse(result)


@app.post("/api/station/{join_code}/{station_id}/heartbeat")
async def api_station_heartbeat(join_code: str, station_id: str):
    sess = control_session.get_by_join_code(join_code)
    if sess and station_id in sess.stations:
        sess.stations[station_id].touch()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, status_code=404)


# ===========================================================================
# MEDSIM 3 ADDITIONS — Integrated EHR layer (Blueprint §§7-13)
# ===========================================================================

# ---- 7. EHR Station Onboarding (QR + URL) --------------------------------

@app.get("/ehr/join", response_class=HTMLResponse)
async def ehr_join_landing(request: Request, code: str | None = None,
                            error: str | None = None):
    """Public EHR landing. No auth — join_code is the access token."""
    return templates.TemplateResponse(
        request, "ehr_join.html",
        {"code": (code or "").upper(), "error": error},
    )


@app.post("/ehr/join")
async def ehr_join_submit(
    request: Request,
    code: Annotated[str, Form()],
    device_label: Annotated[str, Form()] = "",
):
    sess = control_session.get_by_join_code(code)
    if sess is None:
        return RedirectResponse(f"/ehr/join?code={code}&error=notfound", status_code=303)
    if not sess.ehr_id:
        return RedirectResponse(f"/ehr/join?code={code}&error=noehr", status_code=303)
    user_agent = request.headers.get("user-agent", "")[:200]
    ehr_station_id = "ES-" + secrets.token_urlsafe(6)
    sess.add_ehr_station(ehr_station_id, device_label=device_label.strip(), user_agent=user_agent)
    # Persist the station + (if not yet registered) the session+seed.
    _ensure_ehr_session_registered(sess)
    ehr_db.register_station(sess.id, ehr_station_id,
                            device_label=device_label.strip(), user_agent=user_agent)
    return RedirectResponse(f"/ehr/{sess.join_code}/{ehr_station_id}", status_code=303)


def _ensure_ehr_session_registered(sess: control_session.ControlSession) -> None:
    """Lazy-build the ChartSeed + register the ehr_session row on first need."""
    if not sess.ehr_id:
        return
    existing = ehr_db.seed(sess.id)
    if existing:
        return
    seed = ehr_seed.seed_from_session(sess, ehr_id=sess.ehr_id) or {}
    # The EHR session's "primary" persona is the PATIENT — resolve it role-aware
    # (not selected_personas[0], which may be a clinician once one is added).
    primary = ehr_seed.patient_persona_id(sess) or (
        sess.selected_personas[0] if sess.selected_personas else None)
    ehr_db.register_session(sess.id, sess.join_code, sess.ehr_id, primary, seed)


# ---- Launch the EHR locally (instructor convenience — no QR/2nd device) --

_CONTROL_ROOM_EHR_LABEL = "Control room (instructor)"


def _launch_ehr_station(sess: control_session.ControlSession) -> tuple[str, bool]:
    """Register — or reuse — the control-room EHR station for this session.

    Returns (ehr_station_id, reused). A repeat launch reuses the still-
    online control-room station instead of piling up new ones.
    """
    _ensure_ehr_session_registered(sess)
    reused = next((s for s in sess.ehr_stations.values()
                   if s.device_label == _CONTROL_ROOM_EHR_LABEL and s.online), None)
    if reused is not None:
        reused.touch()
        return reused.ehr_station_id, True
    station_id = "ES-" + secrets.token_urlsafe(6)
    sess.add_ehr_station(station_id, device_label=_CONTROL_ROOM_EHR_LABEL,
                         user_agent="control-room-launch")
    ehr_db.register_station(sess.id, station_id,
                            device_label=_CONTROL_ROOM_EHR_LABEL,
                            user_agent="control-room-launch")
    return station_id, False


@app.get("/portal/control/launch_ehr")
async def control_launch_ehr_get(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Register a control-room EHR station and redirect straight into the
    full Medical Records interface — chart, notes, vitals, and order entry
    (labs/imaging/meds).

    Backs the ops-view 'Launch EHR on this device' link. Implemented as a
    plain GET redirect (not a JS popup) so it is an ordinary same-origin
    navigation — no popup-blocker friction and no blank-window base-URL
    pitfalls. Built for testing and small training installs.
    """
    sess = control_session.get_active()
    if sess is None or not sess.ehr_id:
        # Nothing to launch — send the instructor back to the control room.
        return RedirectResponse("/portal/control", status_code=303)
    station_id, _reused = _launch_ehr_station(sess)
    return RedirectResponse(f"/ehr/{sess.join_code}/{station_id}", status_code=303)


@app.post("/portal/control/launch_ehr")
async def control_launch_ehr(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """JSON form of the launch action — registers (or reuses) the control-
    room EHR station and returns its URL. Kept for programmatic callers."""
    sess = control_session.get_active()
    if sess is None:
        raise HTTPException(409, "No active session.")
    if not sess.ehr_id:
        raise HTTPException(
            409, "This session has no EHR configured. Start a session and "
                 "choose a records system in wizard step 2b.")
    station_id, reused = _launch_ehr_station(sess)
    return JSONResponse({
        "ok": True,
        "url": f"/ehr/{sess.join_code}/{station_id}",
        "ehr_id": sess.ehr_id,
        "station_id": station_id,
        "reused": reused,
    })


# ---- M34 — Per-encounter instructor EHR launch (room mode) ----------
#
# `/portal/control/launch_ehr` above is the v6-singleton flavor — it
# calls `control_session.get_active()`, which returns None in a v7
# multi-encounter room (M2 contract). In room mode every bed has its
# own EHR config; the instructor needs to be able to open the chart
# for a specific bed from that bed's Per-Patient Console, in a new
# window.
#
# This is the v7-aware twin: takes an encounter_id, resolves the
# Encounter (which IS a ControlSession dataclass — same dataclass,
# just renamed), and reuses `_launch_ehr_station` verbatim.

@app.get("/portal/room/encounter/{encounter_id}/launch_ehr")
async def room_encounter_launch_ehr_get(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Instructor-only same-origin redirect into the EHR chart for this
    bed. Backs the encounter console's '📋 Open EHR (new window)'
    button — open in a new tab with `target="_blank"` for a side-by-
    side workflow (console on one monitor, EHR on another)."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if not enc.ehr_id:
        # No EHR configured for this bed — send the instructor back to
        # the console with a hint in the query string. The console can
        # surface a "no EHR configured" toast if/when we plumb one.
        return RedirectResponse(
            f"/portal/room/encounter/{encounter_id}?ehr=unconfigured",
            status_code=303,
        )
    station_id, _reused = _launch_ehr_station(enc)
    return RedirectResponse(
        f"/ehr/{enc.join_code}/{station_id}", status_code=303,
    )


@app.post("/portal/room/encounter/{encounter_id}/launch_ehr")
async def room_encounter_launch_ehr_post(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """JSON form of the per-encounter EHR launch — returns the URL
    instead of redirecting. Kept symmetric with the singleton route's
    POST flavor for programmatic callers (e.g. WebDriver flows)."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if not enc.ehr_id:
        raise HTTPException(
            409, "This encounter has no EHR configured. Pick one in the "
                 "wizard's per-row Scenario drawer.")
    station_id, reused = _launch_ehr_station(enc)
    return JSONResponse({
        "ok": True,
        "url":         f"/ehr/{enc.join_code}/{station_id}",
        "ehr_id":      enc.ehr_id,
        "station_id":  station_id,
        "encounter_id": enc.id,
        "reused":      reused,
    })


# ---- Serve the EHR bundle (with Jinja-rendered bootstrap) ----------------

# NOTE — route order matters: the demo route MUST be registered BEFORE
# the generic /ehr/{join_code}/{station_id} or FastAPI's first-match-wins
# resolver will hand `/ehr/demo/helix` to the bundle route with
# join_code="demo", station_id="helix" and trigger a notfound redirect.
@app.get("/ehr/demo/{ehr_id}", response_class=HTMLResponse)
async def ehr_bundle_demo(ehr_id: str, request: Request,
                           _: Annotated[credentials.Vault, Depends(auth.require_vault)]):
    """Operator-only preview of an EHR bundle without an active session.

    Useful for the wizard 'Preview' button so the instructor can see each
    EHR's look before committing. Demo mode: no event POSTs, no heartbeat,
    no chart_event persistence — the React app uses its built-in mockup data.
    """
    if ehr_registry.get(ehr_id) is None:
        raise HTTPException(404, f"Unknown EHR id: {ehr_id}")
    return _render_ehr_bundle(ehr_id, request, mode="demo",
                              join_code="DEMO00", station_id="demo", session=None)


@app.get("/ehr/{join_code}/{station_id}", response_class=HTMLResponse)
async def ehr_bundle(join_code: str, station_id: str, request: Request):
    sess = control_session.get_by_join_code(join_code)
    if sess is None:
        return RedirectResponse(f"/ehr/join?code={join_code}&error=notfound", status_code=303)
    if not sess.ehr_id:
        return RedirectResponse(f"/ehr/join?code={join_code}&error=noehr", status_code=303)
    if station_id not in sess.ehr_stations:
        return RedirectResponse(f"/ehr/join?code={join_code}", status_code=303)
    return _render_ehr_bundle(sess.ehr_id, request, mode="live",
                              join_code=sess.join_code, station_id=station_id,
                              session=sess)


def _render_ehr_bundle(ehr_id: str, request: Request, *, mode: str,
                       join_code: str, station_id: str,
                       session: control_session.ControlSession | None) -> HTMLResponse:
    # V5 — one functional EHR engine themes itself per ehr_id. The bundle
    # is served from portal/ehr/_core/; the ehr_id only needs to be valid.
    if ehr_registry.get(ehr_id) is None:
        raise HTTPException(404, f"Unknown EHR id: {ehr_id}")
    bundle_dir = PORTAL_DIR / "ehr" / "_core"
    if not (bundle_dir / "index.html").exists():
        raise HTTPException(500, "EHR core bundle is missing.")

    bootstrap = _build_bootstrap(ehr_id, mode=mode, join_code=join_code,
                                 station_id=station_id, session=session,
                                 request=request)

    # Render index.html with a single-purpose Jinja env. The template only
    # uses `{{ bootstrap_json | safe }}`; the engine reads EHR_ID out of
    # the bootstrap and picks its theme from themes.js.
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(
        loader=FileSystemLoader(str(bundle_dir)),
        autoescape=select_autoescape(["html"]),
    )
    tmpl = env.get_template("index.html")
    html = tmpl.render(bootstrap_json=json.dumps(bootstrap))
    return HTMLResponse(html)


def _build_bootstrap(ehr_id: str, *, mode: str, join_code: str, station_id: str,
                      session: control_session.ControlSession | None,
                      request: Request) -> dict[str, Any]:
    base = _base_url_for_qr(request)
    out: dict[str, Any] = {
        "MODE":      mode,
        "EHR_ID":    ehr_id,
        "JOIN":      join_code,
        "STATION":   station_id,
        "STATION_LABEL": "",
        "BASE_URL":  base,
        "PATIENTS":  [],
        "SEED":      {},
        "LOCKED":    False,
        "NOW":       int(time.time() * 1000),
    }
    if session is not None and session.ehr_id == ehr_id:
        out["LOCKED"] = session.charting_locked_at is not None
        st = session.ehr_stations.get(station_id)
        if st is not None:
            out["STATION_LABEL"] = st.device_label or ""
        seed = ehr_db.seed(session.id) or {}
        if seed:
            out["SEED"] = seed
            adapter = _adapter_for(ehr_id)
            if adapter is not None:
                try:
                    out["PATIENTS"] = adapter.install(seed).get("patients", []) or []
                except Exception:  # noqa: BLE001 — never break bundle render
                    out["PATIENTS"] = []
    return out


def _adapter_for(ehr_id: str):
    """Lazy-import the EHR's adapter module (helix.adapter, etc.)."""
    try:
        import importlib
        return importlib.import_module(f"portal.ehr.{ehr_id}.adapter")
    except ImportError:
        return None


# ---- 9. API surface for the EHR bundle (event log, heartbeat, chart) -----

@app.get("/api/ehr/{join_code}/{station_id}/bootstrap")
async def api_ehr_bootstrap(join_code: str, station_id: str, request: Request):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or not sess.ehr_id or station_id not in sess.ehr_stations:
        raise HTTPException(404, "Session or station not found.")
    return JSONResponse(_build_bootstrap(
        sess.ehr_id, mode="live", join_code=sess.join_code,
        station_id=station_id, session=sess, request=request,
    ))


@app.post("/api/ehr/{join_code}/{station_id}/event")
async def api_ehr_event(join_code: str, station_id: str, request: Request):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or station_id not in sess.ehr_stations:
        raise HTTPException(404, "Station not found.")
    if sess.charting_locked_at is not None:
        return JSONResponse({"ok": False, "locked": True}, status_code=423)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    ev_type = (body.get("type") or "").strip()
    surface = (body.get("surface") or "").strip()
    if not ev_type or not surface:
        raise HTTPException(400, "Missing 'type' or 'surface'.")
    payload = body.get("payload") or {}
    if "patient_id" in body and "patient_id" not in payload:
        payload["patient_id"] = body.get("patient_id")
    _ensure_ehr_session_registered(sess)
    ev_id = ehr_db.append_event(sess.id, station_id,
                                 type=ev_type, surface=surface, payload=payload)
    sess.ehr_stations[station_id].touch()
    sess.ehr_stations[station_id].event_count += 1
    return JSONResponse({"ok": True, "id": ev_id})


@app.post("/api/ehr/{join_code}/{station_id}/heartbeat")
async def api_ehr_heartbeat(join_code: str, station_id: str):
    sess = control_session.get_by_join_code(join_code)
    if sess and station_id in sess.ehr_stations:
        sess.ehr_stations[station_id].touch()
        ehr_db.touch_station(station_id)
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, status_code=404)


@app.get("/api/ehr/{join_code}/chart/{patient_id}")
async def api_ehr_chart(join_code: str, patient_id: str):
    sess = control_session.get_by_join_code(join_code)
    if sess is None:
        raise HTTPException(404, "Session not found.")
    projection = ehr_db.fold(sess.id)
    projection["patient_id"] = patient_id
    projection["seed"] = ehr_db.seed(sess.id)
    # V5 — surface lock state so an EHR station that is only polling (not
    # writing) still flips read-only when the operator fires lock-in.
    projection["locked"] = sess.charting_locked_at is not None
    return JSONResponse(projection)


def _merged_catalog(ehr_id: str) -> list[dict[str, Any]]:
    """Base per-EHR catalog.json + the persistent master-catalog additions
    (shared across all three records systems)."""
    base = ehr_registry.catalog(ehr_id)
    have = {(i.get("category", ""), str(i.get("code", "")).lower()) for i in base}
    merged = list(base)
    for add in ehr_db.catalog_additions(ehr_id):
        key = (add["category"], add["code"].lower())
        if key not in have:
            merged.append({"code": add["code"], "category": add["category"],
                           "label": add["label"], "common": False,
                           "added": True, "added_by": add.get("added_by", "")})
            have.add(key)
    return merged


@app.get("/api/ehr/{join_code}/orders/catalog")
async def api_ehr_orders_catalog(join_code: str):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or not sess.ehr_id:
        raise HTTPException(404, "Session not found.")
    return JSONResponse({"ehr_id": sess.ehr_id, "items": _merged_catalog(sess.ehr_id)})


@app.post("/api/ehr/{join_code}/orders/catalog")
async def api_ehr_orders_catalog_add(join_code: str, request: Request):
    """Add a custom supply / service / medication to the persistent master
    catalog so it can be ordered from now on, in every EHR."""
    sess = control_session.get_by_join_code(join_code)
    if sess is None or not sess.ehr_id:
        raise HTTPException(404, "Session not found.")
    body = await request.json()
    station_id = (body.get("ehr_station_id") or "").strip()
    added_by = ""
    st = sess.ehr_stations.get(station_id)
    if st is not None:
        added_by = st.device_label or station_id
    item = ehr_db.add_catalog_item(
        body.get("category", ""), body.get("code", ""), body.get("label", ""),
        added_by=added_by or "EHR station")
    if item is None:
        raise HTTPException(400, "category and code are required.")
    return JSONResponse({"ok": True, "item": item,
                         "items": _merged_catalog(sess.ehr_id)})


@app.post("/api/ehr/{join_code}/orders")
async def api_ehr_orders_place(join_code: str, request: Request):
    sess = control_session.get_by_join_code(join_code)
    if sess is None or not sess.ehr_id:
        raise HTTPException(404, "Session not found.")
    if sess.charting_locked_at is not None:
        return JSONResponse({"ok": False, "locked": True}, status_code=423)
    body = await request.json()
    patient_id = body.get("patient_id") or ""
    station_id = body.get("ehr_station_id") or ""
    order = body.get("order") or {}
    if not order:
        raise HTTPException(400, "Missing order body.")
    _ensure_ehr_session_registered(sess)
    ev_id = ehr_db.append_order(sess.id, station_id, patient_id=patient_id, order=order)
    # Auto-promote: an order placed for a code not already in the catalog
    # joins the master list so it "continues forward" as an orderable item.
    code = str(order.get("code", "")).strip()
    category = str(order.get("category", "")).strip().lower()
    if code and category:
        known = {(i.get("category", ""), str(i.get("code", "")).lower())
                 for i in _merged_catalog(sess.ehr_id)}
        if (category, code.lower()) not in known:
            st = sess.ehr_stations.get(station_id)
            ehr_db.add_catalog_item(category, code, order.get("label", code),
                                    added_by=(st.device_label if st else "order"))
    if station_id in sess.ehr_stations:
        sess.ehr_stations[station_id].event_count += 1
        sess.ehr_stations[station_id].touch()
    return JSONResponse({"ok": True, "id": ev_id})


# ---- EHR QR convenience --------------------------------------------------

@app.get("/api/ehr/qr.svg")
async def api_ehr_qr(code: str, request: Request, scale: int = 6):
    """Returns an SVG QR encoding the EHR join URL for a given code."""
    base = _base_url_for_qr(request)
    url = f"{base}/ehr/join?code={code.upper()}"
    svg = qrgen.make_qr_svg(url, scale=scale)
    return Response(content=svg, media_type="image/svg+xml")


# ---- 12. Comparison engine + lock-in (Phase 5 — full impl in compare/) --

@app.post("/portal/control/charting_complete")
async def control_charting_complete(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Fire the lock-in: run rules + rubric, persist comparison_report,
    flip the chart to read-only. Synchronous (3-6s typical)."""
    sess = control_session.get_active()
    if sess is None or not sess.ehr_id:
        raise HTTPException(409, "No active EHR session.")
    if sess.charting_locked_at is not None:
        raise HTTPException(409, "Charting is already locked.")
    _ensure_ehr_session_registered(sess)

    # Lazy import — keeps `compare` optional at startup.
    try:
        from .compare import rules as compare_rules, rubric as compare_rubric, score as compare_score
    except ImportError:
        # Phase 2/3 fallback — record an empty report so the UI flow works
        ehr_db.save_comparison(sess.id, {}, {}, score=0.0, model="stub")
        sess.charting_locked_at = time.time()
        return JSONResponse({"ok": True, "composite": 0.0, "stub": True})

    chart = ehr_db.fold(sess.id)
    orders = ehr_db.orders(sess.id)
    seed = ehr_db.seed(sess.id)

    rules_r = compare_rules.evaluate(sess, chart, orders, seed)
    try:
        rubric_r = await compare_rubric.evaluate(sess, chart, orders, api_key=sess.api_key)
    except Exception as exc:  # noqa: BLE001 — never fail lock-in on a network blip
        rubric_r = {"completeness": 1, "accuracy": 1, "sbar_quality": 1,
                    "prioritization": 1, "safety": 1,
                    "narrative_feedback": f"Rubric unavailable ({type(exc).__name__})."}
    composite = compare_score.composite(rules_r, rubric_r)
    ehr_db.save_comparison(sess.id, rules_r, rubric_r, composite,
                           model="claude-haiku-4-5")
    sess.charting_locked_at = time.time()
    return JSONResponse({"ok": True, "composite": composite})


@app.get("/api/comparison/{session_id}")
async def api_comparison(
    session_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    report = ehr_db.get_comparison(session_id)
    if not report:
        raise HTTPException(404, "No comparison_report for that session.")
    return JSONResponse(report)


# ---- EHR ops view helpers (ops view polls these for the station roster) --

@app.get("/api/ehr/state")
async def api_ehr_state(_: Annotated[credentials.Vault, Depends(auth.require_vault)]):
    sess = control_session.get_active()
    if sess is None:
        return JSONResponse({"active": False})
    stations_payload = []
    for st in sess.ehr_stations.values():
        stations_payload.append({
            "ehr_station_id": st.ehr_station_id,
            "device_label":   st.device_label or "—",
            "online":         st.online,
            "joined_at":      st.joined_at,
            "event_count":    st.event_count,
            "seconds_since_seen": int(time.time() - st.last_seen),
        })
    return JSONResponse({
        "active":  True,
        "ehr_id":  sess.ehr_id,
        "locked":  sess.charting_locked_at is not None,
        "locked_at": sess.charting_locked_at,
        "stations": stations_payload,
        "event_count": sum(s.event_count for s in sess.ehr_stations.values()),
    })


# ---- 18. Operator-only EHR admin (seed inspector + purge) ----------------

@app.get("/portal/ehr_admin", response_class=HTMLResponse)
async def ehr_admin(request: Request,
                     _: Annotated[credentials.Vault, Depends(auth.require_vault)]):
    sess = control_session.get_active()
    seed = ehr_db.seed(sess.id) if sess else {}
    events = ehr_db.events(sess.id) if sess else []
    return templates.TemplateResponse(
        request, "ehr_admin.html",
        {
            "active":  "control",
            "session": sess,
            "ehrs":    ehr_registry.REGISTRY,
            "seed":    seed,
            "events":  events[-50:],  # last 50 only
            "event_total": len(events),
            "storage": ehr_db.storage_status(),   # V5 — persistence health
            "master_catalog": ehr_db.catalog_additions(None),  # V5 Phase 6
        },
    )


@app.post("/portal/ehr_admin/purge")
async def ehr_admin_purge(_: Annotated[credentials.Vault, Depends(auth.require_vault)]):
    sess = control_session.get_active()
    if sess is None:
        return RedirectResponse("/portal/ehr_admin", status_code=303)
    ehr_db.purge_session(sess.id)
    sess.ehr_stations.clear()
    sess.charting_locked_at = None
    return RedirectResponse("/portal/ehr_admin", status_code=303)


@app.post("/portal/ehr_admin/catalog_remove")
async def ehr_admin_catalog_remove(
    item_id: Annotated[int, Form()],
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Instructor prune of a master-catalog addition."""
    ehr_db.remove_catalog_item(item_id)
    return RedirectResponse("/portal/ehr_admin", status_code=303)


# ===========================================================================
# MEDSIM 4 ADDITIONS — ElevenLabs neural character voices
# ===========================================================================

def _session_el_key() -> str:
    """The ElevenLabs key the station-facing /api/tts route should use.

    Stations carry no operator cookie, so they can't reach the vault.
    Prefer the key captured onto the active ControlSession at start;
    fall back to env/keyfile resolution.
    """
    sess = control_session.get_active()
    if sess and sess.elevenlabs_api_key:
        return sess.elevenlabs_api_key
    return voices.get_api_key(None)


# ─────────────────────────────────────────────────────────────────────
# M38 — Process-wide Anthropic key runtime cache.
#
# Mirrors voices.py's `_runtime_key` pattern for ElevenLabs.  Stations
# (which carry no operator cookie) cannot read the vault directly.
# When a station-turn route needs to call Claude, it has two options:
#
#   1. Use the key snapshotted onto the encounter at /api/room/start
#      (`enc.api_key`) — stale if the operator has updated the key
#      since the room launched.
#   2. Use a process-wide cache that any vault-authed route refreshes
#      whenever it reads the latest ANTHROPIC_API_KEY value — so a
#      key update in /portal/credentials propagates to all live
#      encounters without a restart.
#
# We prefer option 2.  The cache is populated every time an operator-
# authenticated route resolves the key (`_capture_anthropic_key` is
# called from /api/room/start, /portal/credentials, etc.).  Empty
# strings never overwrite a previously-cached non-empty value — that
# protects against accidental clears.
# ─────────────────────────────────────────────────────────────────────

_anthropic_runtime_key: str = ""


def _capture_anthropic_key(key: str | None) -> str:
    """Update the process-wide cache with a freshly-resolved Anthropic
    key (typically from `vault.get("ANTHROPIC_API_KEY")`).  Returns the
    (possibly cached) value — empty when never set."""
    global _anthropic_runtime_key
    if key:
        cleaned = key.strip()
        if cleaned:
            _anthropic_runtime_key = cleaned
    return _anthropic_runtime_key


def _resolve_anthropic_key(
    sess: control_session.ControlSession | None,
) -> str:
    """Best-known Anthropic key for a station-turn callsite.

    Order:
      1. Process-wide cache (updated whenever an operator route reads
         the vault — reflects the *current* /portal/credentials value).
      2. Key snapshotted onto the encounter at room start.

    Either may be empty; the caller must handle that and surface a
    friendly error to the chat.
    """
    if _anthropic_runtime_key:
        return _anthropic_runtime_key
    return (sess.api_key if sess else "") or ""


@app.get("/api/voices")
async def api_voices(
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Full voice catalog — live ElevenLabs catalog or static fallback."""
    cat = voices.list_voices(voices.get_api_key(vault))
    return JSONResponse(cat)


@app.get("/api/voices/health")
async def api_voices_health(
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return JSONResponse(voices.health(voices.get_api_key(vault)))


@app.get("/api/voices/candidates")
async def api_voice_candidates_by_traits(
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
    sex: str = "U",
    age_band: str = "middle_aged",
    accent: str = "american",
    ethnicity: str = "anglo_american",
):
    """Up to 5 candidate voices for an arbitrary character (no persona id).

    Used by the legacy V1 voice session, whose characters carry only a
    voice profile. The browser passes the character's traits as query
    params; everything else mirrors the persona-keyed route below.
    """
    traits = {"sex": sex, "age_band": age_band, "accent": accent,
              "ethnicity": ethnicity}
    return JSONResponse(voices.candidates_by_traits(traits, voices.get_api_key(vault)))


@app.get("/api/voices/candidates/{persona_id}")
async def api_voice_candidates(
    persona_id: str,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Up to 5 candidate voices for a persona, ranked by sex/age/ethnicity."""
    return JSONResponse(voices.candidates_for(persona_id, voices.get_api_key(vault)))


@app.post("/api/control/voice")
async def api_control_voice(
    persona_id: Annotated[str, Form()],
    voice_id: Annotated[str, Form()],
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Persist a persona → ElevenLabs voice assignment on the active session.

    voice_id == "" or "browser" stores nothing/empty → browser TTS fallback.
    """
    sess = control_session.get_active()
    if sess is None:
        raise HTTPException(409, "No active session.")
    vid = voice_id.strip()
    if vid in ("", "browser"):
        sess.voice_assignments.pop(persona_id, None)
    else:
        sess.voice_assignments[persona_id] = vid
    return JSONResponse({"ok": True, "persona_id": persona_id,
                         "voice_id": sess.voice_assignments.get(persona_id, "")})


async def _tts_response(text: str, voice_id: str, language: str | None):
    """Shared TTS handler for the GET and POST /api/tts variants.

    On any failure (no key, no voice, ElevenLabs error) returns a 503 with
    {"fallback": true} so the caller degrades to browser SpeechSynthesis.
    On success streams audio/mpeg progressively from Flash v2.5 — the
    GET form lets an <audio> element start playback before the synth
    finishes, which is what keeps perceived latency near 200 ms.
    """
    from fastapi.responses import StreamingResponse

    text = (text or "").strip()
    voice_id = (voice_id or "").strip()
    api_key = _session_el_key()

    if not text or not voice_id or not api_key:
        return JSONResponse(
            {"fallback": True,
             "reason": ("no text" if not text else
                        "no voice_id" if not voice_id else
                        "ElevenLabs not configured")},
            status_code=503,
        )

    # Probe the first chunk so a hard failure (bad key, 4xx) becomes a
    # clean 503+fallback rather than a half-streamed broken response.
    agen = voices.synthesize_stream(text, voice_id, api_key, language=language or None)
    try:
        first = await agen.__anext__()
    except StopAsyncIteration:
        return JSONResponse({"fallback": True, "reason": "empty audio"}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"fallback": True, "reason": type(exc).__name__},
                            status_code=503)

    async def _body():
        yield first
        try:
            async for chunk in agen:
                yield chunk
        except Exception:  # noqa: BLE001 — stream cut mid-flight; client already has audio
            return

    return StreamingResponse(_body(), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store",
                                      "X-MedSim-Voice": voice_id})


@app.get("/api/tts")
async def api_tts_get(text: str, voice_id: str, language: str | None = None):
    """Streaming TTS — station-facing, no auth. Designed for <audio src=…>
    so the browser plays progressively as bytes arrive."""
    return await _tts_response(text, voice_id, language)


@app.post("/api/tts")
async def api_tts_post(request: Request):
    """POST form of /api/tts — body JSON {text, voice_id, language?}.
    Same behavior as the GET form; kept for longer text payloads."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    return await _tts_response(body.get("text", ""), body.get("voice_id", ""),
                               body.get("language"))


# =====================================================================
# V7 — ControlRoom HTTP API (M4)
#
# Eight new routes for the multi-patient layer. None of these have a
# UI yet — the charge-nurse dashboard (M5), the wizard's room-mode
# branch (M6), and the student join flow (M9) consume them. The
# scenes engine palette (M7) replaces the minimal "instructor.trigger"
# event writer below with a richer template-driven palette.
#
# Encounter-level mutations write through ehr_db.append_event so they
# are durable across server restarts (M16 will switch the *delivery*
# from HTTP-poll to WebSocket push, but the persistence path is the
# same).
# =====================================================================


def _encounter_summary(enc: control_room.Encounter) -> dict[str, Any]:
    """Per-encounter row used by GET /api/room/state. Cheap to compute
    on every 2 s poll: counts + last-event timestamp + state, no fold."""
    chart_event_count = len(ehr_db.events(enc.id))
    last_ts = 0.0
    if enc.transcript:
        last_ts = max(last_ts, enc.transcript[-1].ts)
    # M30 — surface lead-student name when set so the dashboard can
    # show a pill without a second round-trip.
    lead_name = None
    room = control_room.get_active_room()
    if room and enc.lead_student_id and enc.lead_student_id in room.students:
        lead_name = room.students[enc.lead_student_id].display_name
    # M53 — free-text lead_label takes priority over the roster-picked
    # name for display purposes (operator most-recently set it). When
    # blank, fall back to the M30 lead_student_name.
    lead_label = (getattr(enc, "lead_label", "") or "").strip()
    effective_lead_display = lead_label or lead_name or ""
    return {
        "encounter_id":   enc.id,
        "join_code":      enc.join_code,
        "label":          enc.encounter_label or enc.scenario_name,
        "scenario_name":  enc.scenario_name,
        "patient_persona_id": enc.patient_persona_id,
        "state":          enc.state,
        "chart_mode":     enc.chart_mode,
        "ehr_id":         enc.ehr_id,
        "chat_stations":  len(enc.stations),
        "ehr_stations":   len(enc.ehr_stations),
        "device_stations": len(enc.device_stations),
        "chart_event_count": chart_event_count,
        "assigned_student_ids": list(enc.assigned_student_ids),
        "lead_student_id":   enc.lead_student_id,
        "lead_student_name": lead_name,
        "lead_label":        lead_label,
        "effective_lead_display": effective_lead_display,
        "last_event_ts":  last_ts,
        # M30 — convenience URLs for the dashboard's pop-out button
        # and the per-encounter chat station entry. The client opens
        # console_url in a popup window for multi-monitor monitoring.
        "console_url":   f"/portal/room/encounter/{enc.id}",
        "station_join_url": f"/join?code={enc.join_code}",
    }


def _room_summary(room: control_room.ControlRoom) -> dict[str, Any]:
    """Aggregate poll body for the charge-nurse dashboard."""
    student_stations = control_room._count_student_stations(room)
    return {
        "room_id":     room.room_id,
        "room_code":   room.room_code,
        "label":       room.label,
        "status":      room.status,
        "created_at":  room.created_at,
        "ended_at":    room.ended_at,
        "haiku_rate_cap":  room.haiku_rate_cap,
        "voice_char_cap":  room.voice_char_cap,
        "encounters":  [_encounter_summary(e) for e in room.encounters.values()],
        "students":    [
            {
                "student_id":             s.student_id,
                "display_name":           s.display_name,
                "assigned_encounter_id":  s.assigned_encounter_id,
                "registered_at":          s.registered_at,
                "last_seen":              s.last_seen,
            }
            for s in room.students.values()
        ],
        # M19 — capacity bar for the dashboard banner.
        "capacity": {
            "encounters_used":         len(room.encounters),
            "encounters_max":          control_room.MAX_ENCOUNTERS_PER_ROOM,
            "student_stations_used":   student_stations,
            "student_stations_max":    control_room.MAX_STUDENT_STATIONS_PER_ROOM,
        },
    }


def _require_active_room() -> control_room.ControlRoom:
    """Helper for room-aggregate routes. 404 when no room is active."""
    room = control_room.get_active_room()
    if room is None:
        raise HTTPException(404, "No active room. Start one via /api/room/start.")
    return room


def _require_encounter(encounter_id: str) -> control_room.Encounter:
    """Helper for /api/encounter/{id}/... routes."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    return enc


def _apply_scene(enc: control_room.Encounter, scene: dict[str, Any],
                  *, by: str) -> dict[str, Any]:
    """Thin wrapper around the M7 scenes engine. Delegates to
    ``portal.scenes.apply`` which dispatches on scene['kind'] to one of
    the 8 built-in handlers (vitals.drop, vitals.rise, lab.result,
    order.new, family.arrives, pump.alarm, code.blue, note.instructor)
    or to the forward-compatibility fallback (one instructor.trigger
    event) for unknown kinds."""
    return scenes.apply(enc, scene, by=by)


@app.post("/api/room/start")
async def api_room_start(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Wizard finalize for multi-encounter mode.

    Body JSON:
      {
        "label": "Morning Shift",
        "encounters": [
          {"scenario_name": "Bed 1 — Diaz",   "persona_id": "P-001", ...},
          {"scenario_name": "Bed 2 — Kowalski", "persona_id": "P-013", ...},
          ...
        ],
        "haiku_rate_cap": null,
        "voice_char_cap": null
      }

    Per-encounter fields mirror the wizard's single-patient
    `/portal/control/start` body: scenario_name, scenario_notes,
    program_id, week, modules, persona_id, ehr_id, scenario_text.
    Each entry becomes one Encounter and gets its own join code.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None

    label = (body.get("label") or "").strip()
    entries = body.get("encounters") or []
    if not isinstance(entries, list) or not entries:
        raise HTTPException(400, "encounters[] must be a non-empty list.")

    # If a room was already active, end it cleanly. Operator demoed,
    # closes the old room, starts a new one.
    if control_room.get_active_room() is not None:
        control_room.end_active_room()
    room = control_room.create_room(label=label)
    room.haiku_rate_cap = body.get("haiku_rate_cap")
    room.voice_char_cap = body.get("voice_char_cap")
    # FR-007 — the universal/shared cast (already merged into each encounter's
    # roster by the wizard); kept room-level so surfaces can separate it out.
    room.shared_personas = [p for p in (body.get("shared_personas") or []) if p]
    try:                                        # a fresh launch isn't a resume (G7)
        from . import session_state as _ss
        _ss.clear_last_resume()
    except Exception:  # noqa: BLE001
        pass

    anthropic_key = (vault.get("ANTHROPIC_API_KEY") or "").strip()
    elevenlabs_key = (vault.get("ELEVENLABS_API_KEY") or "").strip()
    # M38 — Fail fast when no Anthropic key is configured. Without one,
    # every station turn would hit a 401 from Claude with a confusing
    # raw error in the chat. Also seed the process-wide cache so
    # station-turn routes resolve the same key without re-reading vault.
    if not anthropic_key:
        raise HTTPException(
            400,
            "No ANTHROPIC_API_KEY configured. Set it at /portal/credentials "
            "before starting a room — character turns require it.",
        )
    _capture_anthropic_key(anthropic_key)

    created: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise HTTPException(400, "Each encounter entry must be an object.")
        scenario_name = (entry.get("scenario_name") or "").strip()
        if not scenario_name:
            raise HTTPException(400, "Each encounter needs a scenario_name.")
        # M19 — capacity check before constructing the encounter to
        # avoid building an orphan ControlSession object on overflow.
        if len(room.encounters) >= control_room.MAX_ENCOUNTERS_PER_ROOM:
            raise HTTPException(
                409,
                f"Room capacity reached "
                f"({control_room.MAX_ENCOUNTERS_PER_ROOM} encounters max). "
                f"Reduce the encounter count in your wizard finalize."
            )
        enc = control_session.ControlSession(
            id=secrets.token_urlsafe(8),
            join_code=control_session._new_join_code(),
            scenario_name=scenario_name,
            scenario_notes=(entry.get("scenario_notes") or "").strip(),
            program_id=entry.get("program_id"),
            week=entry.get("week"),
            selected_modules=list(entry.get("modules") or []),
            scenario_text=(entry.get("scenario_text") or "").strip(),
            selected_personas=list(entry.get("personas") or []),
            avatar_personas=[
                p for p in (entry.get("avatar_personas") or [])
                if p in set(entry.get("personas") or [])
            ],
            api_key=anthropic_key,
            ehr_id=entry.get("ehr_id"),
            elevenlabs_api_key=elevenlabs_key,
            encounter_label=(entry.get("label") or "").strip(),
            chart_mode=entry.get("chart_mode") or "shared",
            patient_persona_id=entry.get("patient_persona_id")
                                or entry.get("persona_id"),
            activity_id=entry.get("activity_id"),
        )
        room.add_encounter(enc)
        created.append({
            "encounter_id": enc.id,
            "join_code":    enc.join_code,
            "scenario_name": enc.scenario_name,
        })

    return JSONResponse({
        "ok": True,
        "room_id":   room.room_id,
        "room_code": room.room_code,
        "encounters": created,
    })


@app.get("/api/room/state")
async def api_room_state(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Aggregate room poll — the charge-nurse dashboard hits this every
    2 s. Returns the room aggregate + a per-encounter summary row."""
    room = _require_active_room()
    return JSONResponse(_room_summary(room))


@app.get("/api/encounter/{encounter_id}/stations")
async def api_encounter_stations(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 #54 — per-encounter live student-station roster (online / platform /
    turn count) for the encounter console's roster card; the room summary only
    carries counts. Instructor 'Engage' stations are filtered out — this is the
    connected STUDENTS on this bed."""
    import time as _t
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    out: list[dict[str, Any]] = []
    for s in enc.stations.values():
        if (s.user_agent or "") == _INSTRUCTOR_USER_AGENT:
            continue                         # operator's own Engage stations, not students
        persona = library.get_persona(s.persona_id) if s.persona_id else None
        ua = (s.user_agent or "").lower()
        platform = ("iPhone" if "iphone" in ua else "iPad" if "ipad" in ua
                    else "Android" if "android" in ua else "Mac" if "macintosh" in ua
                    else "Windows" if "windows" in ua else "Other")
        out.append({
            "station_id": s.station_id,
            "persona_id": s.persona_id,
            "persona_name": (persona or {}).get("name") if persona else None,
            "persona_role": (persona or {}).get("role", "") if persona else "",
            "platform": platform,
            "online": s.online,
            "turns": len(s.history or []),
            "seconds_since_seen": int(_t.time() - s.last_seen),
        })
    out.sort(key=lambda x: (not x["online"], (x["persona_name"] or "").lower()))
    return JSONResponse({"encounter_id": encounter_id, "stations": out})


@app.post("/api/room/freeze_all")
async def api_room_freeze_all(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Pause every encounter in the active room.

    M16 — also broadcasts a `freeze_all` event over the room WS so
    subscribed stations react in real time (≤500 ms typical).
    Subscribers that miss the push (offline, just (re)loading) catch
    up on the next /api/room/state poll.
    """
    room = _require_active_room()
    room.freeze_all()
    await ws_room.emit_freeze_all(room.room_code,
                                    encounter_count=len(room.encounters))
    return JSONResponse({"ok": True, "status": room.status,
                          "encounter_count": len(room.encounters)})


@app.post("/api/room/resume_all")
async def api_room_resume_all(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Inverse of /api/room/freeze_all. M16 — WS push."""
    room = _require_active_room()
    room.resume_all()
    await ws_room.emit_resume_all(room.room_code,
                                    encounter_count=len(room.encounters))
    return JSONResponse({"ok": True, "status": room.status,
                          "encounter_count": len(room.encounters)})


@app.post("/api/room/end")
async def api_room_end(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """End every encounter in the active room and clear the singleton.

    M15 — Before clearing the singleton, build and save the cohort
    debrief (M14) so it's available at
    `/portal/debrief/cohort/{room_id}` after end. The
    in-memory ControlRoom state is the source of truth for the
    debrief; once the singleton is cleared, that state is gone.
    """
    room = _require_active_room()
    room_id = room.room_id
    encounter_count = len(room.encounters)

    # M15 — build + persist cohort debrief BEFORE end_active_room
    # nukes the singleton. Failures are non-fatal: log and continue
    # so the operator can still end the room cleanly.
    cohort_saved = False
    try:
        cohort = debrief_mod.build_cohort_debrief(room)
        debrief_mod.save_cohort(cohort)
        cohort_saved = True
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"  [warn] cohort debrief save failed for room "
              f"{room_id}: {exc}", file=sys.stderr, flush=True)

    room_code_for_emit = room.room_code  # capture before singleton dies
    control_room.end_active_room()
    # M16 — last broadcast on the way out so stations can show "ended"
    # banners before they reload.
    try:
        await ws_room.emit_room_end(room_code_for_emit,
                                      encounter_count=encounter_count)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({
        "ok": True, "room_id": room_id,
        "encounter_count": encounter_count,
        "cohort_debrief_saved": cohort_saved,
        "cohort_debrief_url": f"/portal/debrief/cohort/{room_id}",
    })


# ─────────────────────────────────────────────────────────────────────
# M35 — Start / Pause / End controls at both room and encounter level,
# plus instructor "engage" auto-stations.
#
# State machine:
#   configured ──Start──▶ running ◀──Pause──▶ paused
#                            │                  │
#                            └───────End ───────┘
#                                  ▼
#                                ended
#
# Master Start (room-wide) is *the* trigger for the entire room: it
# transitions every encounter to running AND auto-registers an
# instructor chat station (id = `INST-{persona_id}`) for every persona
# in every encounter. That station is what the Per-Patient Console's
# Engage button deep-links to — no /join handshake, no name typed.
#
# Per-encounter Start has the same auto-register behavior but scoped
# to one bed. Per-encounter End marks one bed as ended WITHOUT firing
# a cohort debrief — the cohort debrief is only saved when the master
# /api/room/end fires (preserves M15's "save before clear" contract).
# ─────────────────────────────────────────────────────────────────────

_INSTRUCTOR_STATION_PREFIX = "INST-"
_INSTRUCTOR_USER_AGENT = "instructor-engage"


def _instructor_station_id_for(persona_id: str) -> str:
    """Deterministic station id for a given (encounter, persona). Lets
    the engage flow lookup the station by id without scanning."""
    return f"{_INSTRUCTOR_STATION_PREFIX}{persona_id}"


def _ensure_instructor_stations(enc: control_session.ControlSession) -> int:
    """For each persona on this encounter, ensure an instructor chat
    station exists with id `INST-{persona_id}`. Idempotent — repeat
    calls don't create duplicates. Returns the number of stations
    newly created on this call (so callers can log)."""
    created = 0
    for pid in enc.selected_personas:
        sid = _instructor_station_id_for(pid)
        if sid in enc.stations:
            continue
        st = enc.add_station(sid, user_agent=_INSTRUCTOR_USER_AGENT)
        st.persona_id = pid
        created += 1
    return created


def _set_encounter_running_with_instructor_stations(
    enc: control_session.ControlSession,
) -> int:
    """Transition one encounter to 'running' and ensure instructor
    stations exist. Used by both master Start and per-encounter Start.
    No-op for encounters already in 'ended' state."""
    if enc.state == "ended":
        return 0
    enc.state = "running"
    return _ensure_instructor_stations(enc)


@app.post("/api/room/start_all")
async def api_room_start_all(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Master Start — transition every encounter in the active room to
    'running' and auto-register instructor chat stations for every
    persona in every encounter. Idempotent; safe to click twice.

    This is the launchpad for the Engage flow: once Start has fired,
    every persona has an `INST-<pid>` station the instructor can drop
    into directly via `/portal/engage/{encounter_id}/{persona_id}`.
    """
    room = _require_active_room()
    total_created = 0
    for enc in room.encounters.values():
        total_created += _set_encounter_running_with_instructor_stations(enc)
    room.status = "active"
    try:
        await ws_room.emit_start_all(
            room.room_code, encounter_count=len(room.encounters))
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({
        "ok": True,
        "status": room.status,
        "encounter_count": len(room.encounters),
        "instructor_stations_created": total_created,
    })


@app.post("/api/encounter/{encounter_id}/start")
async def api_encounter_start(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Per-encounter Start — same behavior as /api/room/start_all but
    scoped to one bed. Also creates instructor stations for that bed's
    personas so the Engage button on this console works immediately."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    created = _set_encounter_running_with_instructor_stations(enc)
    try:
        await ws_room.emit_encounter_state(
            room.room_code, encounter_id=enc.id, state=enc.state)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({
        "ok": True,
        "state": enc.state,
        "encounter_id": enc.id,
        "instructor_stations_created": created,
    })


@app.post("/api/encounter/{encounter_id}/pause")
async def api_encounter_pause(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Per-encounter Pause — set this encounter's state to 'paused'.
    The room-level status is NOT recomputed (room may still be 'active'
    while one bed is paused). No WS room-wide effect, only an
    encounter-scoped state push."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if enc.state == "ended":
        return JSONResponse({"ok": True, "state": enc.state,
                              "encounter_id": enc.id, "noop": True})
    enc.state = "paused"
    try:
        await ws_room.emit_encounter_state(
            room.room_code, encounter_id=enc.id, state=enc.state)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({
        "ok": True, "state": enc.state, "encounter_id": enc.id,
    })


@app.post("/api/encounter/{encounter_id}/end")
async def api_encounter_end(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Per-encounter End — set this encounter's state to 'ended'.

    Crucially does NOT fire a cohort debrief; the cohort debrief is
    only built when the master /api/room/end fires. Operator semantics:
    you can "wrap up" beds individually as students finish, then call
    the master End once to save the combined PEARLS debrief at the
    point all beds are done.
    """
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    enc.state = "ended"
    try:
        await ws_room.emit_encounter_state(
            room.room_code, encounter_id=enc.id, state=enc.state)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({
        "ok": True, "state": enc.state, "encounter_id": enc.id,
        "cohort_debrief_saved": False,
        "note": "Per-encounter End does not fire a cohort debrief. "
                "Call POST /api/room/end when the whole room is done.",
    })


@app.get("/portal/engage/{encounter_id}/{persona_id}")
async def portal_engage(
    encounter_id: str,
    persona_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Deep-link the instructor into a chat station already bound to
    `persona_id` on this encounter — no /join handshake.

    Auto-creates the instructor station on demand (so Engage works
    even before master Start has fired). Redirects to the standard
    `/station/{join_code}/{station_id}` chat UI, in the same tab
    (the encounter console opens the link with target=_blank).
    """
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if persona_id not in enc.selected_personas:
        raise HTTPException(
            404,
            f"Persona {persona_id!r} is not assigned to encounter "
            f"{encounter_id!r}.",
        )
    sid = _instructor_station_id_for(persona_id)
    if sid not in enc.stations:
        # Lazy-register so the Engage button works even when the
        # instructor clicks it before pressing master Start. Master
        # Start does the bulk registration up-front; this path is the
        # safety net.
        st = enc.add_station(sid, user_agent=_INSTRUCTOR_USER_AGENT)
        st.persona_id = persona_id
    return RedirectResponse(
        f"/station/{enc.join_code}/{sid}", status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────


@app.post("/api/room/scene_broadcast")
async def api_room_scene_broadcast(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Inject a scene into many encounters at once.

    Body: {"scene": {...}, "targets": "all" | [encounter_id, ...]}
    Writes one instructor.trigger chart_event per target. M7's scenes
    engine will expand 'scene' to a templated payload; M4 emits the
    raw scene dict so the wire format is forward-compatible.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None

    room = _require_active_room()
    scene = body.get("scene") or {}
    if not isinstance(scene, dict):
        raise HTTPException(400, "scene must be an object.")
    targets = body.get("targets", "all")
    if targets == "all":
        target_encs = list(room.encounters.values())
    elif isinstance(targets, list):
        target_encs = []
        for eid in targets:
            enc = room.encounters.get(eid)
            if enc is None:
                raise HTTPException(404, f"Unknown encounter {eid!r}.")
            target_encs.append(enc)
    else:
        raise HTTPException(400, "targets must be 'all' or a list of encounter_ids.")

    results = [_apply_scene(enc, scene, by="room_broadcast")
                for enc in target_encs]
    # M16 — push a scene event for every target encounter.
    for enc, result in zip(target_encs, results):
        try:
            await ws_room.emit_scene(room.room_code,
                                      encounter_id=enc.id,
                                      scene=scene, result=result)
        except Exception:  # noqa: BLE001
            pass
    return JSONResponse({"ok": True, "fired": len(results), "results": results})


@app.post("/api/encounter/{encounter_id}/scene")
async def api_encounter_scene(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Inject a scene into a single encounter."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    scene = body.get("scene") or {}
    if not isinstance(scene, dict):
        raise HTTPException(400, "scene must be an object.")
    enc = _require_encounter(encounter_id)
    result = _apply_scene(enc, scene, by="encounter_inject")
    # M16 — single-encounter scene push.
    try:
        room = control_room.get_active_room()
        if room is not None:
            await ws_room.emit_scene(room.room_code,
                                      encounter_id=enc.id,
                                      scene=scene, result=result)
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(result)


@app.post("/api/encounter/{encounter_id}/assign_students")
async def api_encounter_assign_students(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Re-roster students to an encounter.

    Body: {"student_ids": ["...", "..."]}
    The list replaces the current `assigned_student_ids` on the
    encounter and updates each Student.assigned_encounter_id. Unknown
    student_ids 404.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    student_ids = body.get("student_ids") or []
    if not isinstance(student_ids, list):
        raise HTTPException(400, "student_ids must be a list.")

    room = _require_active_room()
    enc = _require_encounter(encounter_id)
    # Validate all IDs first.
    for sid in student_ids:
        if sid not in room.students:
            raise HTTPException(404, f"Unknown student {sid!r}.")
    # Apply: clear old roster on this encounter, set new.
    enc.assigned_student_ids = list(student_ids)
    for sid in student_ids:
        room.students[sid].assigned_encounter_id = enc.id
    # Sweep: students no longer assigned to this encounter that still
    # point here, unassign them.
    for s in room.students.values():
        if s.assigned_encounter_id == enc.id and s.student_id not in student_ids:
            s.assigned_encounter_id = None
    return JSONResponse({
        "ok": True,
        "encounter_id": enc.id,
        "assigned_student_ids": list(enc.assigned_student_ids),
    })


# =====================================================================
# V7 — Charge-nurse dashboard (M5)
#
# The instructor's primary surface in multi-patient mode. A grid of
# Encounter cards under one ControlRoom, polling /api/room/state every
# 2 s, with a top bar of synchronized-control buttons (Freeze All /
# Resume All / Inject Scene / End Room).
#
# This route only serves the HTML scaffold. The Encounter cards are
# rendered client-side by /static/control_room.js from the JSON the
# /api/room/state route returns.
# =====================================================================

@app.get("/portal/room", response_class=HTMLResponse)
async def portal_room(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Charge-nurse dashboard scaffold. Encounter grid is rendered by
    /static/control_room.js from /api/room/state. Empty-state CTA fires
    a quickstart room via /api/room/start when there is no active room.

    M36 — also passes the active room + base_url so the template can
    render a Nursing Station QR + 🩺 Open button (room-wide, not per-
    encounter). Both are `None` when no room is active; template
    blocks below `{% if room %}` keep them hidden in that case.
    """
    room = control_room.get_active_room()
    room_ctx = None
    if room is not None:
        # M53 — surface the encounter list so the template can pre-
        # render the "👤 Lead assignments" panel server-side (one row
        # per encounter). The dashboard's regular state poll still
        # owns the live encounter cards further down; the lead panel
        # is operator-typed text so it doesn't need live refresh.
        encounters_view = [
            {
                "id":               enc.id,
                "encounter_label":  enc.encounter_label or "",
                "scenario_name":    enc.scenario_name,
                "lead_label":       getattr(enc, "lead_label", "") or "",
            }
            for enc in room.encounters.values()
        ]
        room_ctx = {
            "room_code":   room.room_code,
            "room_id":     room.room_id,
            "label":       room.label or "",
            "encounters":  encounters_view,
        }
    resp = templates.TemplateResponse(
        request,
        "control_room.html",
        {
            "active":   "room",
            "room":     room_ctx,
            "base_url": _base_url_for_qr(request),
        },
    )
    # M56-bugfix — never let the dashboard HTML stick in browser
    # cache. Operator-reported bug: a pre-M56 cached page (no
    # encounter checkboxes on the med-cart form) lingered after a
    # JS update, so the submit handler found zero
    # `.med-cart-create-enc-cb:checked` and the server defaulted to
    # linking just the first encounter. The static-asset versioning
    # (?v=mtime) busts JS/CSS but not the HTML that references them,
    # so we add no-store here.
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ─────────────────────────────────────────────────────────────────────
# M61 — Medical Records entry page.
#
# Operator: "Medical records entry page to select from patient
# characters and give status of pending actions – meds, labs etc.
# The MAR ... three shift time structure ... BID, TID, QD ...
# Tube feed and IV the total volume rate, fluid type and any
# associated medication to infused with rate and time and total
# dose. Do both for single patient and multi-patient systems."
#
# /portal/medical_records — picker listing every patient in the
#   active session (single or multi). Shows pending-actions counters.
# /portal/medical_records/{persona_id} — full record: shift-MAR
#   (Day / Evening / Night columns), continuous-infusion details
#   (IV drips), tube-feed details (volume + rate + formula + route).
# ─────────────────────────────────────────────────────────────────────

@app.get("/portal/medical_records", response_class=HTMLResponse)
async def portal_medical_records(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    role: str = "",
    initials: str = "",
    user: str = "",
):
    """Picker view — one row per patient. Gated by an EHR sign-in, mirroring the
    student Records Terminal (#82): identify yourself before charts appear, then
    a nurse identity is scoped to their assigned patients while the supervisor
    view shows all. This page is vault-authed (the instructor), so unrecognized
    initials fall back to the full supervisor view rather than locking out."""
    from portal import medical_records as _mr
    room = control_room.get_active_room()
    ini = (initials or "").upper().strip()[:3]
    all_patients = _mr.patients_for_picker(
        control_room_mod=control_room,
        control_session_mod=control_session,
    )
    state = "no_session"
    patients: list[Any] = []
    signed_name = (user or "").strip()[:80]
    if all_patients:
        mode, member, accessible = _records_scope(room, initials=ini, role=role)
        if mode == "signin":
            state = "signin"
        elif mode == "scoped":
            state = "scoped"
            patients = [p for p in all_patients
                        if p.get("encounter_id") in accessible]
            signed_name = member.display_name or signed_name
            ini = (member.initials or ini).upper()
        else:                  # "all" or "unknown" → the authed instructor sees all
            state = "all"
            patients = all_patients
    return templates.TemplateResponse(
        request, "medical_records.html",
        {"active": "medical_records", "patients": patients, "state": state,
         "signed_name": signed_name,
         "role": (role or "").lower().strip() or "student", "initials": ini},
    )


@app.get("/portal/medical_records/{persona_id}",
        response_class=HTMLResponse)
async def portal_medical_records_chart(
    persona_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Full medical-record view for one patient persona."""
    from portal import ehr_seed as _ehr_seed, medical_records as _mr
    # Find the encounter that owns this persona — works in both
    # single-patient and multi-patient modes.
    encounters: list[Any] = []
    room = control_room.get_active_room()
    if room is not None and room.encounters:
        encounters = list(room.encounters.values())
    else:
        sess = control_session.get_active()
        if sess is not None:
            encounters = [sess]
    target_enc = None
    target_persona = None
    for enc in encounters:
        per_enc = _ehr_seed.seeds_for_patient_only(
            enc, ehr_id=getattr(enc, "ehr_id", None)) or []
        for p in per_enc:
            if p.get("character_id") == persona_id:
                target_enc = enc
                target_persona = p
                break
        if target_persona:
            break
    if not target_persona:
        raise HTTPException(404, f"Unknown patient persona {persona_id!r}.")
    # Build the FULL chart seed so we get labs / vitals / orders, not
    # just the trimmed patient-only seed. `seed_from_session` reuses
    # the same generator the EHR SPA uses.
    full_seed = None
    try:
        full_seed = _ehr_seed.seed_from_session(
            target_enc, ehr_id=getattr(target_enc, "ehr_id", "")) or None
    except Exception:  # noqa: BLE001
        full_seed = None
    # Build per-med view models for the shift-MAR table + the
    # continuous-infusion + PRN sections.
    meds_raw = target_persona.get("medications") or []
    scheduled_meds: list[dict[str, Any]] = []
    continuous_meds: list[dict[str, Any]] = []
    prn_meds: list[dict[str, Any]] = []
    for med in meds_raw:
        vm = _mr.med_view_model(med)
        if vm["is_continuous"]:
            continuous_meds.append({**vm, **_mr.infusion_summary(med)})
        elif vm["is_prn"]:
            prn_meds.append(vm)
        else:
            scheduled_meds.append(vm)
    tube_feeds = [_mr.tube_feed_summary(tf)
                  for tf in ((full_seed or {}).get("tube_feeds") or [])]
    # Pending-status counters for the header.
    status = _mr.patient_status(
        meds_raw, labs=(full_seed or {}).get("labs") or [])
    return templates.TemplateResponse(
        request, "medical_records_chart.html",
        {
            "active":          "medical_records",
            "encounter_id":    getattr(target_enc, "id", ""),
            "encounter_label": (
                getattr(target_enc, "encounter_label", None)
                or getattr(target_enc, "scenario_name", "")
                or ""
            ),
            "persona":         target_persona,
            "status":          status,
            "shifts":          _mr.SHIFTS,
            "scheduled_meds":  scheduled_meds,
            "continuous_meds": continuous_meds,
            "prn_meds":        prn_meds,
            "tube_feeds":      tube_feeds,
            "labs":            (full_seed or {}).get("labs_recent") or (full_seed or {}).get("labs") or [],
            # M63 — Full chart sections from the seed. None of these
            # were surfaced pre-M63; the student saw only the MAR.
            "seed":            full_seed or {},
            "chief_complaint": (full_seed or {}).get("chief_complaint", ""),
            "code_status":     (full_seed or {}).get("code_status", ""),
            "allergies":       (full_seed or {}).get("allergies") or [],
            "problem_list":    (full_seed or {}).get("problem_list") or [],
            "vitals_baseline": (full_seed or {}).get("vitals_baseline") or [],
            "immunizations":   (full_seed or {}).get("immunizations") or [],
            "social_history":  (full_seed or {}).get("social_history") or {},
            "family_history":  (full_seed or {}).get("family_history") or [],
            "surgical_history": (full_seed or {}).get("surgical_history") or [],
            "care_team":       (full_seed or {}).get("care_team") or [],
            "encounter_meta":  (full_seed or {}).get("encounter") or {},
            "notes_recent":    (full_seed or {}).get("notes_recent") or [],
            "iv_fluids":       (full_seed or {}).get("iv_fluids") or [],
            # M62 — operator view: chart_inserts from the encounter
            # (instructor + supervisor + student notes / labs) +
            # the can_edit flag that unlocks the add-lab / add-note
            # forms below the chart.
            "chart_inserts":   [
                ci for ci in getattr(target_enc, "chart_inserts", []) or []
                if ci.get("persona_id") == persona_id
            ],
            "can_edit":        True,
            "edit_author_role": "instructor",
            "edit_author_initials_default": "",
            "workstation_url": "",
        },
    )


# ─────────────────────────────────────────────────────────────────────
# M62 — Medical Records WORKSTATION + admin entry.
#
# Operator: "there needs to be a path to open the system in from the
# multi-patient control screen with both a QR code and button to open
# from the control screen. the entry screen should list the active
# patients characters so that the student or instructor must select
# the patient then enter the medical records system. This will support
# setting up an independent work station that multiple students will
# access to enter patient data ... The instructor should also have a
# special access to all them to insert updates and information likes
# labs that have been generated, or doctors notes ... a designated
# nursing supervisor student should be able access through the nursing
# station a 'administrative portal' to enter labs and make notes ...
# A button on the nursing station that allows the Student Nursing
# supervisor to enter their 2 initials to enter the administrative
# entry to have the medical records open up in new window."
#
# Routes:
#   GET  /students/medical_records?code=<room>           — public workstation
#   GET  /students/medical_records/{persona_id}?...      — public chart
#   POST /api/medical_records/{persona_id}/insert        — add lab/note
#
# All three are room-code-authenticated (no vault cookie required) so
# students can scan a QR from a shared workstation tablet. The
# "?role=supervisor&initials=XX" querystring flag unlocks the
# add-lab/add-note forms for the Nursing Station supervisor.
# ─────────────────────────────────────────────────────────────────────

def _records_scope(room: Any, *, initials: str, role: str):
    """Resolve a student's records access on a shared terminal (#82).

    Parallels the med-cart access model: a shared records terminal requires a
    point-of-entry sign-in, then open access shows every patient while restrict
    access scopes to the signed-in person's roster assignments.

    Returns ``(mode, member, accessible)``:
      - ``"all"``     → see every patient (open access, or an elevated role).
      - ``"scoped"``  → see only the encounter ids in ``accessible`` (set[str]).
      - ``"signin"``  → no identity yet; the terminal must capture name+initials.
      - ``"unknown"`` → restrict access + these initials are not on the roster.
    ``member`` is the matched ``StaffMember`` for ``"scoped"`` else ``None``.
    """
    role_n = (role or "").lower().strip()
    # The instructor's nursing-station "supervisor" button is a trusted entry.
    if role_n in ("supervisor", "instructor", "admin"):
        return ("all", None, None)
    ini = (initials or "").upper().strip()[:3]
    if not ini:
        return ("signin", None, None)
    open_access = bool(getattr(room, "open_med_access", True)) if room is not None else True
    if open_access:
        return ("all", None, None)
    member = None
    if room is not None:
        member = next((s for s in room.staff.values()
                       if (s.initials or "").upper().strip() == ini), None)
    if member is None:
        return ("unknown", None, None)
    return ("scoped", member, set(room.accessible_encounter_ids(member.staff_id)))


@app.get("/students/medical_records", response_class=HTMLResponse)
async def students_medical_records_entry(
    request: Request,
    code: str = "",
    role: str = "",
    initials: str = "",
    user: str = "",
):
    """Public workstation entry — no vault auth. A shared terminal: the
    student signs in (name + initials), then sees the patients they're
    cleared for — every patient under open access, only their roster
    assignments under restrict access (#82)."""
    from portal import medical_records as _mr
    room = control_room.get_active_room()
    # Validate room code if provided; if room exists, accept either
    # the active room's code OR a missing code (single-patient v6).
    if code and room is not None and (code or "") != (room.room_code or ""):
        # Wrong code → empty state.
        room = None
    ini = (initials or "").upper().strip()[:3]
    active = room is not None or control_session.get_active() is not None
    state = "no_session"
    patients: list[Any] = []
    signed_name = (user or "").strip()[:80]
    if active:
        all_patients = _mr.patients_for_picker(
            control_room_mod=control_room,
            control_session_mod=control_session,
        )
        mode, member, accessible = _records_scope(room, initials=ini, role=role)
        state = mode
        if mode == "all":
            patients = all_patients
        elif mode == "scoped":
            patients = [p for p in all_patients
                        if p.get("encounter_id") in accessible]
            signed_name = member.display_name or signed_name
            ini = (member.initials or ini).upper()
    return templates.TemplateResponse(
        request, "medical_records_workstation.html",
        {
            "room_code":     code or (room.room_code if room else ""),
            "patients":      patients,
            "state":         state,
            "signed_name":   signed_name,
            "role":          (role or "").lower().strip() or "student",
            "initials":      ini,
        },
    )


@app.get("/students/medical_records/{persona_id}",
        response_class=HTMLResponse)
async def students_medical_records_chart(
    persona_id: str,
    request: Request,
    code: str = "",
    user: str = "",
    initials: str = "",
    role: str = "student",
):
    """Public chart view for a single patient. Same shift-MAR / IV /
    tube-feed / labs UI as the operator chart, plus inline add-note
    / add-lab forms gated by `role in ('instructor', 'supervisor')`.
    """
    from portal import ehr_seed as _ehr_seed, medical_records as _mr
    # Resolve room + encounter — same logic as the operator chart.
    encounters: list[Any] = []
    room = control_room.get_active_room()
    if room is not None and room.encounters:
        encounters = list(room.encounters.values())
    else:
        sess = control_session.get_active()
        if sess is not None:
            encounters = [sess]
    target_enc = None
    target_persona = None
    for enc in encounters:
        per_enc = _ehr_seed.seeds_for_patient_only(
            enc, ehr_id=getattr(enc, "ehr_id", None)) or []
        for p in per_enc:
            if p.get("character_id") == persona_id:
                target_enc = enc
                target_persona = p
                break
        if target_persona:
            break
    if not target_persona:
        raise HTTPException(404, f"Unknown patient persona {persona_id!r}.")
    # #82 — records access control. The chart is where full PHI renders, so
    # enforce scope HERE (not just in the picker) to close direct-link access:
    # on a restrict-access room a signed-in nurse may open only their assigned
    # patients; charge_nurse / supervisor / instructor (and open access) see all.
    if room is not None:
        _mode, _member, _accessible = _records_scope(
            room, initials=initials, role=role)
        if _mode in ("signin", "unknown") or (
                _mode == "scoped"
                and getattr(target_enc, "id", "") not in _accessible):
            raise HTTPException(
                403, "This patient is not assigned to you. Return to the "
                     "records terminal and sign in.")
    full_seed = None
    try:
        full_seed = _ehr_seed.seed_from_session(
            target_enc, ehr_id=getattr(target_enc, "ehr_id", "")) or None
    except Exception:  # noqa: BLE001
        full_seed = None
    meds_raw = target_persona.get("medications") or []
    scheduled_meds: list[dict[str, Any]] = []
    continuous_meds: list[dict[str, Any]] = []
    prn_meds: list[dict[str, Any]] = []
    for med in meds_raw:
        vm = _mr.med_view_model(med)
        if vm["is_continuous"]:
            continuous_meds.append({**vm, **_mr.infusion_summary(med)})
        elif vm["is_prn"]:
            prn_meds.append(vm)
        else:
            scheduled_meds.append(vm)
    tube_feeds = [_mr.tube_feed_summary(tf)
                  for tf in ((full_seed or {}).get("tube_feeds") or [])]
    status = _mr.patient_status(
        meds_raw, labs=(full_seed or {}).get("labs") or [])
    role_norm = (role or "student").lower().strip()
    can_edit = role_norm in ("instructor", "supervisor", "admin")
    chart_inserts = [
        ci for ci in getattr(target_enc, "chart_inserts", []) or []
        if ci.get("persona_id") == persona_id
    ]
    return templates.TemplateResponse(
        request, "medical_records_workstation_chart.html",
        {
            "room_code":     code or "",
            "encounter_id":  getattr(target_enc, "id", ""),
            "encounter_label": (
                getattr(target_enc, "encounter_label", None)
                or getattr(target_enc, "scenario_name", "")
                or ""
            ),
            "persona":       target_persona,
            "status":        status,
            "shifts":        _mr.SHIFTS,
            "scheduled_meds":  scheduled_meds,
            "continuous_meds": continuous_meds,
            "prn_meds":        prn_meds,
            "tube_feeds":      tube_feeds,
            "labs":            (full_seed or {}).get("labs_recent") or (full_seed or {}).get("labs") or [],
            # M63 — Full chart sections from the seed (see operator
            # route comment).
            "seed":            full_seed or {},
            "chief_complaint": (full_seed or {}).get("chief_complaint", ""),
            "code_status":     (full_seed or {}).get("code_status", ""),
            "allergies":       (full_seed or {}).get("allergies") or [],
            "problem_list":    (full_seed or {}).get("problem_list") or [],
            "vitals_baseline": (full_seed or {}).get("vitals_baseline") or [],
            "immunizations":   (full_seed or {}).get("immunizations") or [],
            "social_history":  (full_seed or {}).get("social_history") or {},
            "family_history":  (full_seed or {}).get("family_history") or [],
            "surgical_history": (full_seed or {}).get("surgical_history") or [],
            "care_team":       (full_seed or {}).get("care_team") or [],
            "encounter_meta":  (full_seed or {}).get("encounter") or {},
            "notes_recent":    (full_seed or {}).get("notes_recent") or [],
            "iv_fluids":       (full_seed or {}).get("iv_fluids") or [],
            "chart_inserts":   chart_inserts,
            "can_edit":        can_edit,
            "user":            (user or "").strip(),
            "initials":        (initials or "").upper().strip()[:3],
            "role":            role_norm,
        },
    )


@app.post("/api/medical_records/{persona_id}/insert")
async def api_medical_records_insert(
    persona_id: str,
    request: Request,
):
    """Append a chart insert (lab result, doctor's note, free-text
    update) to the encounter that owns this persona. Body:
        {kind: "note"|"lab"|"doctor_note",
         title: str, body: str,
         author_name: str, author_initials: str,
         author_role: "instructor"|"supervisor"|"student"}

    No vault auth — workstation flow uses room_code + author
    identity in the body. The instructor flow (from
    /portal/medical_records/{persona_id}) hits the same endpoint
    with author_role=instructor; that's gated client-side because
    the operator already proved identity by logging into the vault."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    kind = (body.get("kind") or "note").lower().strip()
    if kind not in {"note", "lab", "doctor_note"}:
        raise HTTPException(400, f"Unknown insert kind {kind!r}.")
    title = (body.get("title") or "").strip()[:200]
    body_text = (body.get("body") or "").strip()
    if not body_text and kind != "lab":
        raise HTTPException(400, "Body required for notes.")
    if kind == "lab" and not title:
        raise HTTPException(400, "Lab name (title) required.")
    author_name = (body.get("author_name") or "").strip()[:80]
    author_initials = (body.get("author_initials") or ""
                        ).upper().strip()[:3]
    author_role = (body.get("author_role") or "student"
                    ).lower().strip()
    # Find the encounter that owns persona_id.
    from portal import ehr_seed as _ehr_seed
    encounters: list[Any] = []
    room = control_room.get_active_room()
    if room is not None and room.encounters:
        encounters = list(room.encounters.values())
    else:
        sess = control_session.get_active()
        if sess is not None:
            encounters = [sess]
    target_enc = None
    for enc in encounters:
        per_enc = _ehr_seed.seeds_for_patient_only(
            enc, ehr_id=getattr(enc, "ehr_id", None)) or []
        if any(p.get("character_id") == persona_id for p in per_enc):
            target_enc = enc
            break
    if target_enc is None:
        raise HTTPException(404, f"Unknown patient persona {persona_id!r}.")
    if not hasattr(target_enc, "chart_inserts") or target_enc.chart_inserts is None:
        target_enc.chart_inserts = []
    import time as _time
    insert = {
        "ts":              _time.time(),
        "kind":            kind,
        "persona_id":      persona_id,
        "title":           title or kind.capitalize(),
        "body":            body_text,
        "author_name":     author_name,
        "author_initials": author_initials,
        "author_role":     author_role,
    }
    target_enc.chart_inserts.append(insert)
    return JSONResponse({"ok": True, "insert": insert,
                          "total": len(target_enc.chart_inserts)})


# ─────────────────────────────────────────────────────────────────────
# M41 — Printable QR sheet for the instructor.
#
# Optional ?encounter_id=<id> scopes the sheet to one bed; without it,
# every encounter in the active room gets its own page. The template
# renders one section per encounter with Chat / EHR / Device / Nursing
# Station QR codes, page-break-after between sections, and a header
# carrying the patient character + "Training Bridge MedSim-VRAI"
# title. Browser print (Cmd/Ctrl+P) sends to paper or PDF.
# ─────────────────────────────────────────────────────────────────────

@app.get("/portal/control/qr_print", response_class=HTMLResponse)
async def portal_control_qr_print(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    encounter_id: str | None = None,
):
    """Print-friendly QR sheet. Scoped to one encounter via the
    `encounter_id` query param; without it, prints every encounter
    in the active room."""
    room = control_room.get_active_room()
    if room is None:
        return templates.TemplateResponse(
            request, "qr_print.html",
            {"room_code": "—", "encounters": [],
             "base_url": _base_url_for_qr(request),
             "scope_label": "no active room"},
        )
    # Hydrate the encounter list — one or all, depending on scope.
    if encounter_id:
        enc = room.encounters.get(encounter_id)
        if enc is None:
            raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
        target_encs = [enc]
        scope_label = "single encounter"
    else:
        # Skip clone encounters (private_clone mode spawns per-student
        # clones from a template; the template is what the operator
        # cares about for QR distribution).
        target_encs = [
            e for e in room.encounters.values()
            if not (e.chart_mode == "private_clone" and e.cloned_from_id)
        ]
        scope_label = f"all {len(target_encs)} encounters"
    # Each template row needs the patient character display name +
    # role hydrated. The encounter only carries patient_persona_id.
    # M46 — also include the encounter's bound device stations so the
    # print sheet can show each device's QR (operators can stick the
    # QR on the actual hardware or hand the sheet to the bedside).
    # FR-007 — separate the shared/universal cast from per-bed scenario cast so
    # the sheet can group patient items under each character and print common
    # items (shared characters + common devices) once.
    shared_set = set(getattr(room, "shared_personas", []) or [])
    avatar_set: set[str] = set()
    for enc in target_encs:
        avatar_set.update(enc.avatar_personas or [])

    def _char_view(pid: str) -> dict[str, Any]:
        pp = library.get_persona(pid) or {}
        return {"id": pid, "name": pp.get("name") or pid, "role": pp.get("role") or "",
                "is_avatar": pid in avatar_set}        # avatar (animated) vs voice-only

    # V1..Vn for duplicate scenario-char NAMES across beds (a "concerned wife" in
    # two patients' scenarios = two people), mirroring the wizard's designation.
    def _scen_pids(enc):
        return [pid for pid in (enc.selected_personas or [])
                if pid != enc.patient_persona_id and pid not in shared_set]
    _name_count: dict[str, int] = {}
    for enc in target_encs:
        for pid in _scen_pids(enc):
            nm = (library.get_persona(pid) or {}).get("name") or pid
            _name_count[nm] = _name_count.get(nm, 0) + 1
    _seen: dict[str, int] = {}
    _sc_variant: dict[tuple, str] = {}
    for enc in target_encs:
        for pid in _scen_pids(enc):
            nm = (library.get_persona(pid) or {}).get("name") or pid
            if _name_count[nm] > 1:
                _seen[nm] = _seen.get(nm, 0) + 1
                _sc_variant[(enc.id, pid)] = "V" + str(_seen[nm])

    enc_views: list[dict[str, Any]] = []
    for enc in target_encs:
        p = library.get_persona(enc.patient_persona_id) if enc.patient_persona_id else None
        devices_view: list[dict[str, str]] = []
        for sid, ds in enc.device_stations.items():
            if ds.device_kind == "cabinet":            # the med cart prints under Common
                continue
            devices_view.append({
                "station_id":   sid,
                "device_kind":  ds.device_kind,
                "device_model": ds.device_model,
                "label":        ds.label or ds.device_model,
            })
        scenario_chars = []
        for pid in _scen_pids(enc):
            cv = _char_view(pid)
            cv["variant"] = _sc_variant.get((enc.id, pid), "")
            scenario_chars.append(cv)
        enc_views.append({
            "id":                  enc.id,
            "join_code":           enc.join_code,
            "scenario_name":       enc.scenario_name,
            "label":               enc.encounter_label,
            "ehr_id":              enc.ehr_id,
            "patient_persona_id":  enc.patient_persona_id,
            "patient_name":        p.get("name") if p else "",
            "patient_role":        p.get("role") if p else "",
            "devices":             devices_view,
            "scenario_chars":      scenario_chars,
        })

    # Common characters (shared cast) + common carts (M47 cart links).
    common_characters = [_char_view(pid) for pid in (getattr(room, "shared_personas", []) or [])]
    common_scenario_id = target_encs[0].id if target_encs else ""
    target_ids = {e.id for e in target_encs}
    common_carts: list[dict[str, str]] = []
    for sid, linked in (getattr(room, "cart_links", {}) or {}).items():
        if not linked or (encounter_id and not (set(linked) & target_ids)):
            continue
        primary = room.encounters.get(linked[0])
        if primary is None:
            continue
        common_carts.append({
            "station_id": sid,
            "label":      (room.cart_labels or {}).get(sid) or "Med cart",
            "join_code":  primary.join_code,
        })
    return templates.TemplateResponse(
        request, "qr_print.html",
        {
            "room_code":          room.room_code,
            "encounters":         enc_views,
            "common_characters":  common_characters,
            "common_scenario_id": common_scenario_id,
            "common_carts":       common_carts,
            "base_url":           _base_url_for_qr(request),
            "scope_label":        scope_label,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# M36 — Instructor convenience: open the Nursing Station in a new
# window without going through the public /portal/students/join role
# picker. Auto-creates (or reuses) a nurse-station student named
# "Instructor (Nursing Station)" and 303s into the supervisor view.
# ─────────────────────────────────────────────────────────────────────

_INSTRUCTOR_NURSE_STATION_NAME = "Instructor (Nursing Station)"


@app.get("/portal/control/launch_nurse_station")
async def portal_control_launch_nurse_station(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Instructor-only convenience: redirect into the Nursing Station
    supervisor view as if the instructor had registered themselves
    through /portal/students/register_nurse.

    Re-used across repeat clicks: searches for an existing nurse-
    station student whose `display_name == "Instructor (Nursing
    Station)"`; if found, redirects to its `sid` URL; otherwise
    creates one. Same pattern as M34's `_launch_ehr_station` (which
    looks up by `device_label == "Control room (instructor)"`).
    """
    room = control_room.get_active_room()
    if room is None:
        # No active room — bounce back to the dashboard so the
        # instructor can start one. Mirrors /portal/control/launch_ehr
        # behavior on the same edge case.
        return RedirectResponse("/portal/room", status_code=303)
    # Look for a previously-created instructor nurse-station student.
    student = None
    for s in room.students.values():
        if (s.role == "nurse_station"
                and s.display_name == _INSTRUCTOR_NURSE_STATION_NAME):
            student = s
            break
    if student is None:
        # M19 station-cap check.
        if (control_room._count_student_stations(room)
                >= control_room.MAX_STUDENT_STATIONS_PER_ROOM):
            raise HTTPException(
                409,
                f"Room is full "
                f"({control_room.MAX_STUDENT_STATIONS_PER_ROOM} student "
                f"stations max). Ask your instructor.")
        student = room.add_student(
            _INSTRUCTOR_NURSE_STATION_NAME, role="nurse_station",
        )
    return RedirectResponse(
        f"/portal/students/nurse_station?sid={student.student_id}",
        status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────
# M48 — Room-level alarm thresholds (settable on the Nursing Station).
#
# The Nursing Station's settings card POSTs operator-chosen low/high
# bounds for HR / SpO2 / RR plus a "dangerous rhythms" list to the
# room-level `alarm_thresholds` dict. The alarm bus (`alarms.py`)
# checks every encounter's telemetry snapshot against these on each
# /api/room/alarms read, raising threshold-breach alarms that flow
# through the same M26 dashboard pipeline.
# ─────────────────────────────────────────────────────────────────────

@app.get("/api/room/alarm_thresholds")
async def api_room_alarm_thresholds_get(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    room = _require_active_room()
    return JSONResponse({"thresholds": room.alarm_thresholds})


@app.post("/api/room/alarm_thresholds")
async def api_room_alarm_thresholds_set(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Operator updates the room's alarm thresholds. The body is the
    full thresholds dict (or a partial update — keys not present are
    left untouched). Per-metric bounds: {"low": int|null, "high": int|null}
    where null means "no bound on that side"."""
    room = _require_active_room()
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object.")
    # Sanity-check the per-metric bounds. M50 adds bp_systolic +
    # bp_diastolic to the validated set.
    for metric in ("hr", "spo2", "rr", "bp_systolic", "bp_diastolic"):
        if metric not in body:
            continue
        bounds = body.get(metric) or {}
        if not isinstance(bounds, dict):
            raise HTTPException(400, f"{metric} must be a {{low, high}} object.")
        for side in ("low", "high"):
            v = bounds.get(side)
            if v is not None:
                try:
                    bounds[side] = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(
                        400, f"{metric}.{side} must be a number or null.",
                    ) from None
        room.alarm_thresholds[metric] = bounds
    if "dangerous_rhythms" in body:
        rhythms = body.get("dangerous_rhythms") or []
        if not isinstance(rhythms, list):
            raise HTTPException(400, "dangerous_rhythms must be a list.")
        room.alarm_thresholds["dangerous_rhythms"] = [
            str(r) for r in rhythms
        ]
    return JSONResponse({"ok": True, "thresholds": room.alarm_thresholds})


# ─────────────────────────────────────────────────────────────────────
# M47 — Room-level med carts.
#
# A single cabinet (device_kind="cabinet", device_model="pyxis") can
# serve MULTIPLE encounters in the same room. The cart's DB row uses
# ONE encounter as its `session_id` (the primary — needed for v6-style
# per-station device routes), but `room.cart_links[cart_sid]` carries
# the full list of linked encounters. The cabinet bootstrap reads
# that list to render a grouped-per-patient MAR. Dispense events
# write a transcript entry to the linked encounter that owns the
# selected patient persona.
# ─────────────────────────────────────────────────────────────────────


def _find_room_cart(room: control_room.ControlRoom, cart_sid: str) -> str | None:
    """Sanity helper: returns cart_sid if it's a known room-level cart,
    None otherwise. Use in routes that look up by cart id."""
    if cart_sid in room.cart_links:
        return cart_sid
    return None


# ── Med cart v2 (#77) — shared-terminal access: open vs assigned roster ──────
#
# Open (default): any student signs in at the cart / records terminal with their
# name + initials and reaches every patient. Restricted: each roster member
# (student or group) is scoped to their assigned patients; charge_nurse /
# supervisor / instructor see all. The cart + records read room.open_med_access
# + the staff roster (control_room.StaffMember).

def _persist_room_quiet() -> None:
    try:
        from portal import session_state as _ss
        _ss.persist()
    except Exception:  # noqa: BLE001 — best-effort
        pass


@app.get("/api/room/staff")
async def api_room_staff_list(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """The room roster + access mode + encounters, for the dashboard panel."""
    room = _require_active_room()
    staff = [{
        "staff_id": sm.staff_id, "display_name": sm.display_name,
        "initials": sm.initials, "role": sm.role,
        "assignments": list(sm.assignments),
    } for sm in room.staff.values()]
    encounters = [{
        "encounter_id": e.id,
        "label": (e.encounter_label or e.scenario_name or e.id),
    } for e in room.encounters.values()]
    return JSONResponse({
        "ok": True,
        "open_med_access": getattr(room, "open_med_access", True),
        "staff": staff,
        "encounters": encounters,
    })


@app.post("/api/room/med_access")
async def api_room_med_access(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Set the shared-terminal access mode. Body: {"open": true|false}."""
    room = _require_active_room()
    body = await request.json()
    room.open_med_access = bool(body.get("open", True))
    _persist_room_quiet()
    return JSONResponse({"ok": True, "open_med_access": room.open_med_access})


@app.post("/api/room/staff")
async def api_room_staff_add(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Add a person/group to the roster. Body: {display_name, initials, role,
    assignments:[encounter_id]}."""
    room = _require_active_room()
    body = await request.json()
    name = (body.get("display_name") or "").strip()
    if not name:
        raise HTTPException(400, "display_name required.")
    sm = room.add_staff(
        name,
        initials=(body.get("initials") or "").strip(),
        role=(body.get("role") or "nurse").strip(),
        assignments=list(body.get("assignments") or []),
    )
    _persist_room_quiet()
    return JSONResponse({"ok": True, "staff_id": sm.staff_id})


@app.post("/api/room/staff/{staff_id}/assignments")
async def api_room_staff_assignments(
    staff_id: str, request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Replace a roster member's patient (encounter) assignments.
    Body: {encounter_ids:[...]}"""
    room = _require_active_room()
    if staff_id not in room.staff:
        raise HTTPException(404, "Unknown staff member.")
    body = await request.json()
    room.set_staff_assignments(staff_id, list(body.get("encounter_ids") or []))
    _persist_room_quiet()
    return JSONResponse({"ok": True})


@app.post("/api/room/staff/{staff_id}/update")
async def api_room_staff_update(
    staff_id: str, request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Patch a roster member's display_name / initials / role (any subset)."""
    room = _require_active_room()
    if staff_id not in room.staff:
        raise HTTPException(404, "Unknown staff member.")
    body = await request.json()
    room.update_staff(
        staff_id,
        display_name=body.get("display_name"),
        initials=body.get("initials"),
        role=body.get("role"),
    )
    _persist_room_quiet()
    return JSONResponse({"ok": True})


@app.delete("/api/room/staff/{staff_id}")
async def api_room_staff_remove(
    staff_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Remove a roster member."""
    room = _require_active_room()
    room.remove_staff(staff_id)
    _persist_room_quiet()
    return JSONResponse({"ok": True})


# ── FR-013a — Local-context library (P1: program-wide CRUD) ─────────────
# Standing orders / formulary / treatment priorities the clinical turn consults
# AFTER best practice. Authored + reviewed, instructor-only, and NOT session-
# scoped — a program-wide library that persists across sessions + the reset.sh
# clean slate. Active items form the overlay a session toggles on (P5) and every
# turn path injects (P4). Nothing applies until an item is marked active.

@app.get("/api/local-context/items")
async def api_local_context_list(
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    from . import local_context as _lc
    items = _lc.list_items()
    return JSONResponse({
        "items": items,
        "types": list(_lc.ITEM_TYPES),
        "enabled": _lc.is_enabled(),                                  # P5 toggle state
        "active_count": sum(1 for it in items if it.get("active")),
    })


@app.post("/api/local-context/enabled")
async def api_local_context_set_enabled(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """FR-013 P5 — flip the program-wide LOCAL-PRACTICE overlay on/off from the
    Set-up page. Persisted; every character-turn path reads it at turn time."""
    from . import local_context as _lc
    body = await request.json()
    enabled = _lc.set_enabled(bool(body.get("enabled")))
    return JSONResponse({"ok": True, "enabled": enabled,
                         "active_count": len(_lc.active_items())})


@app.post("/api/local-context/items")
async def api_local_context_add(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    from . import local_context as _lc
    body = await request.json()
    try:
        item = _lc.add_item(
            type=str(body.get("type") or ""),
            title=str(body.get("title") or ""),
            content=str(body.get("content") or ""),
            source=str(body.get("source") or "manual"),
            active=bool(body.get("active")),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"ok": True, "item": item})


@app.patch("/api/local-context/items/{item_id}")
async def api_local_context_update(
    item_id: str, request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    from . import local_context as _lc
    body = await request.json()
    try:
        item = _lc.update_item(
            item_id,
            type=body.get("type"), title=body.get("title"),
            content=body.get("content"), source=body.get("source"),
            active=body.get("active"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if item is None:
        raise HTTPException(404, "Unknown local-context item.")
    return JSONResponse({"ok": True, "item": item})


@app.delete("/api/local-context/items/{item_id}")
async def api_local_context_remove(
    item_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    from . import local_context as _lc
    if not _lc.remove_item(item_id):
        raise HTTPException(404, "Unknown local-context item.")
    return JSONResponse({"ok": True})


# ── FR-013b Scenario Studio — guided AI scenario generation ─────────────────

@app.post("/api/scenario-studio/generate")
async def api_scenario_studio_generate(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Draft a scenario from the instructor's guided inputs (premise, patient,
    local factors). Returns the draft for review/edit — saving is a separate,
    confirmed step (FR-008 posture). The active local-context items + the inline
    local factors ground the draft in this site's practice (FR-013)."""
    from . import scenario_gen
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    key = (vault.get("ANTHROPIC_API_KEY") or "") or (_resolve_anthropic_key(None) or "")
    if not key:
        return JSONResponse(
            {"ok": False, "error": "No Anthropic API key configured. Add it at "
             "/portal/credentials, then try again."}, status_code=200)
    try:
        draft = scenario_gen.generate(body, api_key=key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — API/parse failure → clean message, not a 500
        return JSONResponse({"ok": False, "error": f"Generation failed: {e}"}, status_code=200)
    return JSONResponse({"ok": True, "draft": draft})


@app.post("/api/scenario-studio/save")
async def api_scenario_studio_save(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Persist a REVIEWED draft as a first-class scenario (+ its synthesized
    personas). It then appears in the launch wizard's Scenario step, pre-fills the
    cast, and seeds the EHR from the patient persona + narrative. This is the
    explicit confirm step (FR-008 'nothing live until confirmed')."""
    from . import authored_content
    try:
        draft = await request.json()
    except Exception:  # noqa: BLE001
        draft = {}
    try:
        record = authored_content.create_from_draft(draft)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"ok": True, "scenario": {
        "id": record["id"], "name": record["name"], "personas": record["personas"]}})


@app.post("/api/room/med_cart/register")
async def api_room_med_cart_register(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Operator creates a room-level med cart on Multi-Patient Control.

    Body: {"label": "Cart A", "encounter_ids": ["E-..", ...]}
    `encounter_ids` may be empty (link later); the first listed
    encounter becomes the cart's primary `session_id` in the DB.
    """
    room = _require_active_room()
    body = await request.json()
    label = (body.get("label") or "").strip() or "Med cart"
    requested_eids: list[str] = list(body.get("encounter_ids") or [])
    # Validate every requested encounter exists in this room.
    for eid in requested_eids:
        if eid not in room.encounters:
            raise HTTPException(
                400,
                f"Encounter {eid!r} is not part of this room.",
            )
    # Need at least one encounter to anchor the device_station's
    # session_id — if none requested, default to the first encounter
    # so the DB row is satisfiable. The cart_links list stays whatever
    # the operator asked for (may be empty until they link below).
    if room.encounters:
        primary_eid = requested_eids[0] if requested_eids else next(iter(room.encounters))
    else:
        raise HTTPException(
            409,
            "Room has no encounters yet. Add an encounter via the wizard before "
            "creating a med cart.",
        )
    primary_enc = room.encounters[primary_eid]
    # Mint the device station against the primary encounter so v6
    # per-station routes (inject/clear/assign) keep working without
    # any new code path. M43's _session_for_station() already finds
    # the right session via station.session_id.
    station_id = "cart_" + secrets.token_hex(6)
    ehr_db.register_device_station(
        primary_enc.id, station_id,
        device_kind="cabinet", device_model="pyxis",
        label=label, user_agent="instructor-create",
    )
    primary_enc.add_device_station(
        station_id,
        device_kind="cabinet", device_model="pyxis",
        label=label, user_agent="instructor-create",
    )
    # Record the room-level link list (everything requested, plus the
    # primary if it wasn't already in the list).
    link_list = list(requested_eids)
    if primary_eid not in link_list:
        link_list.insert(0, primary_eid)
    room.cart_links[station_id] = link_list
    room.cart_labels[station_id] = label
    # Build a QR for the cart's device-join URL — same shape as the
    # M46 per-encounter device QR. The cart uses the PRIMARY encounter's
    # join code (one cart's QR can't carry many join codes; the cart
    # is unlocked by the primary encounter's scope and the cabinet
    # bootstrap pulls all linked encounters' MARs).
    base = _base_url_for_qr(request).rstrip("/")
    join_url = (
        f"{base}/device/join?code={primary_enc.join_code}"
        f"&station={station_id}"
    )
    # M59 — direct device URL bypasses the /device/join landing page
    # so the instructor's "🛒 Open cart" launch button drops straight
    # into the cabinet tablet UI in a new window. Same path the QR
    # would land on after the operator confirms on the landing page.
    device_url = (
        f"{base}/device/{primary_enc.join_code}/{station_id}"
    )
    qr_svg = qrgen.make_qr_svg(join_url)
    return JSONResponse({
        "ok":            True,
        "station_id":    station_id,
        "label":         label,
        "primary_encounter_id": primary_eid,
        "linked_encounter_ids": list(link_list),
        "join_url":      join_url,
        "device_url":    device_url,
        "qr_svg":        qr_svg,
    })


@app.post("/api/room/med_cart/{cart_sid}/link_encounter")
async def api_room_med_cart_link(
    cart_sid: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Add an encounter to a cart's link list. Idempotent — adding
    an already-linked encounter is a no-op."""
    room = _require_active_room()
    if _find_room_cart(room, cart_sid) is None:
        raise HTTPException(404, f"Unknown cart {cart_sid!r}.")
    body = await request.json()
    eid = (body.get("encounter_id") or "").strip()
    if eid not in room.encounters:
        raise HTTPException(400,
                             f"Encounter {eid!r} is not part of this room.")
    links = room.cart_links[cart_sid]
    if eid not in links:
        links.append(eid)
    return JSONResponse({
        "ok": True, "station_id": cart_sid,
        "linked_encounter_ids": list(links),
    })


@app.delete("/api/room/med_cart/{cart_sid}/link_encounter/{eid}")
async def api_room_med_cart_unlink(
    cart_sid: str,
    eid: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Remove an encounter from a cart's link list. The cart's
    primary encounter (its DB session_id) cannot be unlinked — operator
    must delete the cart instead. Returns the updated link list."""
    room = _require_active_room()
    if _find_room_cart(room, cart_sid) is None:
        raise HTTPException(404, f"Unknown cart {cart_sid!r}.")
    station = ehr_db.get_device_station(cart_sid)
    if station and station.get("session_id") == eid:
        raise HTTPException(
            409,
            "Cannot unlink the cart's primary encounter. Delete the "
            "cart instead — it'll be recreated against a different bed.",
        )
    links = room.cart_links[cart_sid]
    if eid in links:
        links.remove(eid)
    return JSONResponse({
        "ok": True, "station_id": cart_sid,
        "linked_encounter_ids": list(links),
    })


@app.get("/api/room/med_carts")
async def api_room_med_carts(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """List every room-level cart with its linked encounters + QR URL.
    Used by the Multi-Patient Control dashboard panel + each encounter
    console's "Linked med carts" read-only block."""
    room = _require_active_room()
    base = _base_url_for_qr(request).rstrip("/")
    out: list[dict[str, Any]] = []
    for cart_sid, link_list in room.cart_links.items():
        station = ehr_db.get_device_station(cart_sid) or {}
        primary_eid = station.get("session_id") or (link_list[0] if link_list else "")
        primary_enc = room.encounters.get(primary_eid)
        join_url = (
            f"{base}/device/join?code={primary_enc.join_code}&station={cart_sid}"
            if primary_enc else ""
        )
        # M59 — direct cart tablet URL, bypasses /device/join landing.
        # Used by the dashboard's "🛒 Open cart" launch button.
        device_url = (
            f"{base}/device/{primary_enc.join_code}/{cart_sid}"
            if primary_enc else ""
        )
        out.append({
            "station_id":           cart_sid,
            "label":                room.cart_labels.get(cart_sid) or station.get("label") or "Med cart",
            "primary_encounter_id": primary_eid,
            "linked_encounter_ids": list(link_list),
            "join_url":             join_url,
            "device_url":           device_url,
        })
    return JSONResponse({"carts": out})


# =====================================================================
# V7 — Scenes palette (M7)
#
# Client-facing endpoint that lists the built-in scene templates. The
# charge-nurse dashboard's scene-injector dialog currently hard-codes
# the same list in JS; a follow-up makes it fetch this endpoint so the
# palette is server-authoritative (then operators can author Activity-
# scoped scenes via M11/M12 without re-deploying the client).
# =====================================================================

@app.get("/api/scenes/palette")
async def api_scenes_palette(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    return JSONResponse({"palette": scenes.palette()})


# =====================================================================
# V7 — Student join flow (M9)
#
# Students scan the room QR (or are handed the URL) and arrive at
# /portal/students/join?code=ROOM_CODE — a PUBLIC page (no operator
# vault required). They see the room's encounter list and either
# pick a preloaded name from the roster or type a free-form display
# name, then pick an encounter. The POST handler:
#   1. Registers/locates the Student in the M1 student table.
#   2. Assigns them to the chosen encounter.
#   3. Creates a chat Station on that encounter (the encounter's
#      patient persona becomes the conversational partner).
#   4. Returns a redirect_url that lands the student on the existing
#      v6 chat-station UI (/station/{join_code}/{station_id}).
# =====================================================================

def _room_by_code(room_code: str) -> control_room.ControlRoom | None:
    """Resolve a room by its operator-displayed room_code. Returns
    None when the code does not match the active room. Single-instructor
    model: at most one active room at a time."""
    room = control_room.get_active_room()
    if room is None:
        return None
    if (room_code or "").strip().upper() != (room.room_code or "").upper():
        return None
    return room


@app.get("/portal/students/join", response_class=HTMLResponse)
async def portal_students_join(request: Request, code: str | None = None):
    """Student-facing join landing. Public — no operator auth.

    Query string ``?code=ROOM_CODE`` carries the room code from the QR
    (the instructor's dashboard displays this code). If the code is
    missing or unknown, the page renders an error state with a prompt
    to re-scan; we never redirect, so a wrong code in the QR is
    debuggable by the student.
    """
    raw = (code or "").strip().upper()
    room = _room_by_code(raw) if raw else None
    if room is None:
        return templates.TemplateResponse(
            request, "student_join.html",
            {"room_code": raw, "room": None, "encounters": [],
              "roster": [], "error": "Room not found." if raw else None},
        )
    return templates.TemplateResponse(
        request, "student_join.html",
        {
            "room_code":  room.room_code,
            "room": {
                "room_id":   room.room_id,
                "room_code": room.room_code,
                "label":     room.label or "",
                "status":    room.status,
            },
            "encounters": [
                {
                    "encounter_id": enc.id,
                    "join_code":    enc.join_code,
                    "label":        enc.encounter_label or enc.scenario_name,
                    "scenario":     enc.scenario_name,
                    "persona_id":   enc.patient_persona_id,
                    "ehr_id":       enc.ehr_id,
                    "students":     len(enc.assigned_student_ids),
                    "state":        enc.state,
                    "chart_mode":   enc.chart_mode,
                }
                # M13 — private-clone templates show in the picker;
                # individual clones do not (each clone belongs to one
                # student already).
                for enc in room.encounters_for_join_picker()
            ],
            # Pre-loaded roster names (any students already registered to
            # this room by the operator). Each entry carries student_id
            # so the join can reattach to an existing row rather than
            # create a duplicate.
            "roster": [
                {"student_id": s.student_id,
                 "display_name": s.display_name,
                 "assigned_encounter_id": s.assigned_encounter_id}
                for s in room.students.values()
            ],
            "error": None,
        },
    )


@app.post("/portal/students/register")
async def portal_students_register(request: Request):
    """Register-or-reattach a student, assign them to an encounter,
    create a chat Station on that encounter, return a redirect URL.

    Form body:
      ``room_code``       — required.
      ``encounter_id``    — required.
      ``display_name``    — required if ``existing_student_id`` is empty.
      ``existing_student_id`` — optional; reattach to an existing row.

    Public — no operator auth. The room_code itself is the access
    token, matching the v6 ``/join`` flow's contract.
    """
    form = await request.form()
    room_code         = (form.get("room_code") or "").strip().upper()
    encounter_id      = (form.get("encounter_id") or "").strip()
    display_name      = (form.get("display_name") or "").strip()
    existing_sid      = (form.get("existing_student_id") or "").strip()

    room = _room_by_code(room_code)
    if room is None:
        raise HTTPException(404, "Unknown room code.")
    if encounter_id not in room.encounters:
        raise HTTPException(404, "Unknown encounter for this room.")
    # M19 — station capacity gate. Counts chat stations across every
    # encounter in the room (clones included). Pre-checks before the
    # private-clone branch below, since cloning + station-add together
    # would consume two seats if we left the check too late.
    if (control_room._count_student_stations(room)
            >= control_room.MAX_STUDENT_STATIONS_PER_ROOM):
        raise HTTPException(
            409,
            f"Room is full ("
            f"{control_room.MAX_STUDENT_STATIONS_PER_ROOM} student "
            f"stations max). Ask your instructor for guidance."
        )

    # Resolve the Student — either reattach to an existing row or
    # register a new one. Free-form names are allowed (matches the
    # v6 mobile-station UX — no class-list pre-load required).
    if existing_sid:
        student = room.students.get(existing_sid)
        if student is None:
            raise HTTPException(404, "Unknown student id.")
        # Honor an updated display name if provided.
        if display_name and display_name != student.display_name:
            student.display_name = display_name
    else:
        if not display_name:
            raise HTTPException(400, "display_name required for a new student.")
        student = room.add_student(display_name)

    # M13 — private-clone branch. When the picked encounter is a
    # private_clone template (chart_mode='private_clone' AND
    # cloned_from_id=None), spawn a fresh clone per student. The
    # student joins the clone, not the template; subsequent students
    # who pick the same template each get their own clone.
    target_enc = room.encounters[encounter_id]
    if (target_enc.chart_mode == "private_clone"
            and target_enc.cloned_from_id is None):
        target_enc = room.clone_encounter(
            encounter_id, label_suffix=student.display_name,
        )
        # Make sure the clone has its own EHR seed registered before
        # the student lands on its chart station; otherwise the EHR
        # bundle would 404 on first hit. _ensure_ehr_session_registered
        # uses the encounter's own id so each clone gets independent
        # chart_event rows.
        _ensure_ehr_session_registered(target_enc)

    room.assign_student(student.student_id, target_enc.id)

    # Create the chat Station on the chosen encounter. The encounter's
    # patient persona is the conversational partner — the student does
    # NOT pick a persona (room-mode encounters have exactly one).
    persona_id = target_enc.patient_persona_id or (
        target_enc.selected_personas[0] if target_enc.selected_personas else None
    )
    if not persona_id:
        raise HTTPException(409, "Encounter has no patient persona configured.")
    station_id = secrets.token_urlsafe(8)
    station = target_enc.add_station(
        station_id,
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    station.persona_id = persona_id

    return JSONResponse({
        "ok":            True,
        "student_id":    student.student_id,
        "display_name":  student.display_name,
        "encounter_id":  target_enc.id,
        "station_id":    station_id,
        "redirect_url":  f"/station/{target_enc.join_code}/{station_id}",
        # M13 — true when the student joined a private clone (the
        # picker showed them the template, the server cloned it,
        # and the redirect points at the clone).
        "is_clone":      target_enc.cloned_from_id is not None,
        "cloned_from_id": target_enc.cloned_from_id,
    })


# =====================================================================
# V7 — Activity catalog HTTP API (M12)
#
# CRUD on the M11 activity catalog. The wizard's room-mode Step 4r
# fetches GET /api/activities to populate the per-row Activity
# picker; PATCH/POST/DELETE land Author / Edit / Delete features
# (the dashboard UI is M5 follow-up — until then operators can
# curl-edit).
# =====================================================================

@app.get("/api/activities")
async def api_activities_list(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    builtin_only: bool = False,
):
    """List every activity in the catalog. Default ordering: built-ins
    first (alphabetical), then custom (alphabetical)."""
    return JSONResponse({
        "activities": ehr_db.list_activities(builtin_only=builtin_only),
    })


@app.get("/api/activities/{activity_id}")
async def api_activities_get(
    activity_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    row = ehr_db.get_activity(activity_id)
    if row is None:
        raise HTTPException(404, f"Unknown activity {activity_id!r}.")
    return JSONResponse(row)


@app.post("/api/activities")
async def api_activities_create(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Create a custom activity (always `is_builtin=False`). Body JSON
    mirrors the dataclass: label (required), seed_persona_id,
    seed_modules[], scenario_text, default_chart_mode, answer_key."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(400, "label is required.")
    chart_mode = body.get("default_chart_mode", "shared")
    if chart_mode not in ("shared", "private_clone"):
        raise HTTPException(400, "default_chart_mode must be "
                                  "'shared' or 'private_clone'.")
    row = ehr_db.create_activity(
        label=label,
        seed_persona_id=body.get("seed_persona_id") or None,
        seed_modules=list(body.get("seed_modules") or []),
        scenario_text=(body.get("scenario_text") or "").strip(),
        default_chart_mode=chart_mode,
        answer_key=body.get("answer_key"),
        is_builtin=False,  # public-route creates are never builtin
    )
    return JSONResponse(row)


@app.patch("/api/activities/{activity_id}")
async def api_activities_patch(
    activity_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Patch a subset of fields. Unknown fields silently ignored
    (forward-compat). Returns the updated row or 404."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    updated = ehr_db.update_activity(activity_id, **body)
    if updated is None:
        raise HTTPException(404, f"Unknown activity {activity_id!r}.")
    return JSONResponse(updated)


@app.delete("/api/activities/{activity_id}")
async def api_activities_delete(
    activity_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Delete a custom activity. Returns 409 if the activity is a
    built-in (protected). Idempotent on missing rows (returns 200)."""
    existing = ehr_db.get_activity(activity_id)
    if existing is not None and existing["is_builtin"]:
        raise HTTPException(409, "Built-in activities cannot be deleted. "
                                  "PATCH it to edit its fields instead.")
    ehr_db.delete_activity(activity_id)
    return JSONResponse({"ok": True, "activity_id": activity_id})


@app.get("/api/activities/{activity_id}/encounter_entry")
async def api_activities_to_encounter_entry(
    activity_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Translate an activity into the encounter-row dict the wizard
    needs for `/api/room/start`. Convenience for the wizard JS — it
    can also assemble this client-side, but the round-trip keeps the
    mapping authoritative server-side."""
    entry = activities.to_encounter_entry(activity_id)
    if entry is None:
        raise HTTPException(404, f"Unknown activity {activity_id!r}.")
    return JSONResponse(entry)


# =====================================================================
# V7 — Cohort debrief UI (M15)
# =====================================================================

@app.get("/portal/debrief/cohort/{room_id}", response_class=HTMLResponse)
async def portal_cohort_debrief(
    room_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Render a saved cohort debrief (M14 JSON) as the PEARLS-tabbed
    web view. 404 when no saved debrief exists for that room_id
    (the operator either never ended the room or the save failed)."""
    data = debrief_mod.load_cohort(room_id)
    if data is None:
        raise HTTPException(404, f"No cohort debrief saved for room {room_id!r}.")
    return templates.TemplateResponse(
        request, "debrief_cohort.html",
        {"active": "debrief", "cohort": data, "room_id": room_id},
    )


@app.get("/api/debrief/cohort/{room_id}")
async def api_cohort_debrief(
    room_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """JSON read of a saved cohort debrief."""
    data = debrief_mod.load_cohort(room_id)
    if data is None:
        raise HTTPException(404, f"No cohort debrief saved for room {room_id!r}.")
    return JSONResponse(data)


@app.post("/api/debrief/cohort/{room_id}/notes")
async def api_cohort_debrief_save_notes(
    room_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Persist instructor notes added during the live debrief —
    Reactions.notes and Application.commitments. Body:
        {"reactions_notes": "...", "commitments": ["...", ...]}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    data = debrief_mod.load_cohort(room_id)
    if data is None:
        raise HTTPException(404, f"No cohort debrief saved for room {room_id!r}.")
    pearls = data.setdefault("pearls", {})
    if "reactions_notes" in body:
        pearls.setdefault("reactions", {})["notes"] = str(body["reactions_notes"])
    if "commitments" in body and isinstance(body["commitments"], list):
        pearls.setdefault("application", {})["commitments"] = [
            str(x) for x in body["commitments"]
        ]
    debrief_mod.save_cohort(data)
    return JSONResponse({"ok": True})


# =====================================================================
# V7 Phase 7 — Per-Patient Console (M22 scaffold + M25 rich features)
# =====================================================================

@app.get("/portal/room/encounter/{encounter_id}",
        response_class=HTMLResponse)
async def portal_room_encounter_console(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Instructor drill-in for one encounter. Per-patient telemetry
    preview (M23), ECG strip (M24), device list (M1.5 + M25),
    telemetry overrides + scene injector (M25). M22 ships the
    scaffold; subsequent modules light up each card."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    # V8 — personas with a VRAI Faces avatar QR (one tablet-pairing code each,
    # resolved to display names). The PATIENT is the primary bedside avatar, so
    # it ALWAYS gets an avatar-rig QR here even if it was never opted in via the
    # wizard — the card-launch/resume path could leave enc.avatar_personas without
    # the patient, which made the patient's rig-launch QR vanish from the controls
    # (field report 2026-06). Patient first, then the opted-in secondary avatars.
    _avatar_pids = list(enc.avatar_personas or [])
    if enc.patient_persona_id and enc.patient_persona_id not in _avatar_pids:
        _avatar_pids.insert(0, enc.patient_persona_id)
    avatar_personas_detail = [
        {"id": pid,
         "name": (library.get_persona(pid) or {}).get("name") or pid,
         "is_patient": (pid == enc.patient_persona_id)}
        for pid in _avatar_pids
    ]
    # Shows per-character device QRs — ensure the avatar app is up + LAN-reachable.
    _ensure_vrai_app_for_qr(request)
    # FR-011 — context-aware Back: opened from the new Mission Control card
    # (?return=console) → return to the card pages; otherwise the classic room.
    if (request.query_params.get("return") or "") == "console":
        back_url, back_label = "/portal/console?mode=operate", "← Back to Mission Control"
    else:
        back_url, back_label = "/portal/room", "← Back to Multi-Patient Control"
    return templates.TemplateResponse(
        request, "encounter_console.html",
        {
            "active": "room",
            "encounter": enc,
            "avatar_personas_detail": avatar_personas_detail,
            "room": {"room_code": room.room_code,
                      "label":     room.label or "",
                      "room_id":   room.room_id},
            # M31 — base_url is used by the QR-codes card so each
            # station's join URL is LAN-reachable (matches v6 ops
            # view's QR rendering).
            "base_url": _base_url_for_qr(request),
            "back_url": back_url,
            "back_label": back_label,
        },
    )


# =====================================================================
# V7 Phase 7 — Future-device stubs (M29)
# =====================================================================

@app.get("/api/future_devices/kinds")
async def api_future_devices_kinds(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Public list of the 4 M29 future-device kinds with labels."""
    return JSONResponse({
        "kinds": [{"id": k, "label": v}
                   for k, v in future_devices_mod.KINDS.items()],
    })


@app.post("/api/encounter/{encounter_id}/future_device/{kind}/press")
async def api_future_device_press(
    encounter_id: str,
    kind: str,
    request: Request,
):
    """Public — a bedside future-device button-press emits an
    alarm.injected device_event that the M26 alarm bus surfaces to
    the Nursing Station and the operator dashboard. The body's
    `by` field (default 'bedside') is recorded for audit."""
    try:
        body = await request.json() if (
            request.headers.get("content-type", "")
            .startswith("application/json")) else {}
    except Exception:
        body = {}
    by = (body.get("by") or "bedside").strip()
    room = control_room.get_active_room()
    if room is None:
        raise HTTPException(404, "No active room.")
    try:
        result = future_devices_mod.press(room, encounter_id, kind, by=by)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    # Push WS so the nurse station sees the alarm immediately.
    try:
        await ws_room.manager.broadcast(room.room_code, {
            "type":         "future_device_press",
            "encounter_id": encounter_id,
            "payload":      {"kind": kind, "by": by,
                              "event_id": result.get("id")},
        })
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({"ok": True, "kind": kind,
                          "encounter_id": encounter_id,
                          "event_id": result.get("id")})


# =====================================================================
# V7 Phase 7 — Intercom (M28)
# =====================================================================

@app.post("/api/intercom/{encounter_id}/page")
async def api_intercom_page(
    encounter_id: str,
    request: Request,
):
    """Public — the Nursing Station student posts a message that
    plays at the bedside chat station. Body:
        {"text": "...", "from_student_id": "stu_xxx", "voice_id": "..."}

    Authentication is by the from_student_id existing on the active
    room as a nurse_station-role student. The room_code itself is
    not required because we already have a per-student token from
    M27's register_nurse flow."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required.")
    room = control_room.get_active_room()
    if room is None:
        raise HTTPException(404, "No active room.")
    if encounter_id not in room.encounters:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    from_sid = (body.get("from_student_id") or "").strip()
    if from_sid:
        student = room.students.get(from_sid)
        if student is None or student.role != "nurse_station":
            raise HTTPException(
                403, "from_student_id must reference an active "
                      "nurse-station student in this room.")
    try:
        result = intercom_mod.page_encounter(
            room, encounter_id,
            text=text,
            from_student_id=from_sid or None,
            voice_id=body.get("voice_id"),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None
    # M16 WS push so the bedside chat station knows to play it.
    try:
        await ws_room.manager.broadcast(room.room_code, {
            "type":         "intercom",
            "encounter_id": encounter_id,
            "payload":      {"event_id": result.get("event_id"),
                              "text":     text,
                              "voice_id": result.get("voice_id"),
                              "persona_id": result.get("persona_id")},
        })
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(result)


# =====================================================================
# V7 Phase 7 — Nursing Station student role (M27)
# =====================================================================

@app.post("/portal/students/register_nurse")
async def portal_students_register_nurse(request: Request):
    """Register a student in the in-sim Nursing Station role.

    Body fields:
      room_code     — required
      display_name  — required for new; may be omitted with existing_student_id
      existing_student_id — optional

    Differs from /portal/students/register (M9) in two ways:
      1. The student is NOT assigned to an encounter. The Nursing
         Station role is room-scoped — they monitor every bed.
      2. No chat station is created. The student lands directly on
         /portal/students/nurse_station?sid=… and polls the room.

    Public (no operator auth). The room_code is the access token.
    """
    form = await request.form()
    room_code    = (form.get("room_code") or "").strip().upper()
    display_name = (form.get("display_name") or "").strip()
    existing_sid = (form.get("existing_student_id") or "").strip()
    room = _room_by_code(room_code)
    if room is None:
        raise HTTPException(404, "Unknown room code.")

    if existing_sid:
        student = room.students.get(existing_sid)
        if student is None:
            raise HTTPException(404, "Unknown student id.")
        if display_name and display_name != student.display_name:
            student.display_name = display_name
        student.role = "nurse_station"
    else:
        if not display_name:
            raise HTTPException(400, "display_name required for a new nurse-station student.")
        # M19 station-cap check — nurse station counts toward the
        # room's 24-station cap.
        if (control_room._count_student_stations(room)
                >= control_room.MAX_STUDENT_STATIONS_PER_ROOM):
            raise HTTPException(
                409,
                f"Room is full "
                f"({control_room.MAX_STUDENT_STATIONS_PER_ROOM} student "
                f"stations max). Ask your instructor.")
        student = room.add_student(display_name, role="nurse_station")

    return JSONResponse({
        "ok":           True,
        "student_id":   student.student_id,
        "display_name": student.display_name,
        "role":         "nurse_station",
        "redirect_url": f"/portal/students/nurse_station?sid={student.student_id}",
    })


@app.get("/portal/students/nurse_station", response_class=HTMLResponse)
async def portal_students_nurse_station(
    request: Request,
    sid: str | None = None,
):
    """Public nurse-station landing. Requires the student_id (sid)
    query param so the page can identify which student is at this
    seat. No operator auth — the sid acts as the seat token."""
    if not sid:
        raise HTTPException(400, "sid query param required.")
    room = control_room.get_active_room()
    if room is None:
        raise HTTPException(404, "No active room.")
    student = room.students.get(sid)
    if student is None or student.role != "nurse_station":
        raise HTTPException(404, "Unknown nurse-station student.")
    return templates.TemplateResponse(
        request, "nurse_station.html",
        {
            "student": student,
            "room":    {"room_code": room.room_code,
                         "room_id":   room.room_id,
                         "label":     room.label or ""},
        },
    )


# =====================================================================
# V7 Phase 7 — Alarm bus (M26)
# =====================================================================

@app.get("/api/room/alarms")
async def api_room_alarms(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Active alarms across every encounter in the room. Polled by
    M27 Nursing Station every 2 s. Read-only — observer accessible."""
    room = _require_active_room()
    return JSONResponse({"alarms": alarms_mod.active_alarms(room)})


@app.post("/api/alarm/{alarm_id}/clear")
async def api_alarm_clear(
    alarm_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Clear one alarm. Writes a synthetic alarm.cleared event so
    the next /api/room/alarms read filters it out. 404 on unknown
    alarm_id or after the active room ends.

    M50 — Threshold alarms (which have no event log to write into)
    are now also supported: they're added to `room.silenced_alarms`
    with `cleared=True` so they're filtered out of the active feed.
    """
    room = _require_active_room()
    result = alarms_mod.clear_alarm(room, alarm_id)
    if result is None:
        raise HTTPException(404, f"Unknown alarm id {alarm_id!r}.")
    return JSONResponse(result)


@app.post("/api/room/encounter/{encounter_id}/clear_alarms")
async def api_encounter_clear_alarms(encounter_id: str):
    """Bedside 'Clear alarms' (Integrated Com & Alarm device) — silences THIS
    bed's call-bell / bed-alarm / intercom alerts from the room itself, like a
    real wall console when staff enter. Public (room-code trust, same model as
    the PIA buttons). Clears DEVICE-source alarms only; code-blue + physiologic
    threshold alarms intentionally persist (cleared by the team / nurse station)."""
    room = control_room.get_active_room()
    if room is None or encounter_id not in room.encounters:
        raise HTTPException(404, "Unknown encounter.")
    cleared = 0
    for a in alarms_mod.active_alarms(room):
        if a.get("encounter_id") == encounter_id and a.get("source") == "device":
            if alarms_mod.clear_alarm(room, str(a.get("alarm_id") or "")):
                cleared += 1
    try:
        await ws_room.manager.broadcast(room.room_code, {
            "type": "alarms_cleared", "encounter_id": encounter_id, "count": cleared})
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse({"ok": True, "cleared": cleared})


# ─────────────────────────────────────────────────────────────────────
# M50 — Silence an alarm (audio mute without removing from board).
# Works on any source (device, scene, threshold). Default duration
# is 45 s (M52 — was 120 s before; operator: "silence of an alarm
# last 45 seconds then it goes active if the condition is not
# resolved or cleared"). Operator can still pass ?seconds=N to
# override for an individual press.
# ─────────────────────────────────────────────────────────────────────

@app.post("/api/alarm/{alarm_id}/silence")
async def api_alarm_silence(
    alarm_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
    seconds: int = 45,
):
    room = _require_active_room()
    result = alarms_mod.silence_alarm(
        room, alarm_id, duration_s=seconds,
    )
    if result is None:
        raise HTTPException(404, f"Unknown alarm id {alarm_id!r}.")
    return JSONResponse(result)


# ─────────────────────────────────────────────────────────────────────
# M50 — Nurse Station can fire a Code Blue at a specific encounter.
#
# Auth shape:
#   - Operator (instructor cookie): always allowed.
#   - Nurse-station student: pass `nurse_sid` in the JSON body; the
#     route validates the sid against the active room's nurse_station-
#     role students. This is the only scene a non-instructor can
#     trigger.
# ─────────────────────────────────────────────────────────────────────

@app.post("/api/room/encounter/{eid}/nurse_code_blue")
async def api_room_nurse_code_blue(
    eid: str,
    request: Request,
    medsim_session: Annotated[str | None, Cookie()] = None,
):
    room = _require_active_room()
    enc = room.encounters.get(eid)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {eid!r}.")
    # Auth: operator cookie wins. Otherwise look for nurse_sid in body.
    is_operator = auth.verify_session(medsim_session)
    by_label = "instructor"
    if not is_operator:
        try:
            body = await request.json()
        except Exception:
            body = {}
        nurse_sid = (body.get("nurse_sid") or "").strip()
        if not nurse_sid:
            raise HTTPException(
                401,
                "Must be authenticated as instructor OR pass nurse_sid "
                "in the body (Nursing Station flow).",
            )
        student = room.students.get(nurse_sid)
        if student is None or student.role != "nurse_station":
            raise HTTPException(
                403,
                "nurse_sid is not a registered Nursing Station student "
                "for this room.",
            )
        by_label = f"nurse_station:{nurse_sid}"
    # Fire the code.blue scene at the named encounter — same scene
    # the instructor would inject via /api/encounter/{id}/scene.
    from portal import scenes as _scenes
    result = _scenes.apply(
        enc, {"kind": "code.blue", "params": {}}, by=by_label,
    )
    return JSONResponse({
        "ok": True, "encounter_id": eid, "scene": "code.blue",
        "by": by_label, "result": result,
    })


# =====================================================================
# V7 Phase 7 — ECG waveform library (M24)
# =====================================================================

@app.get("/api/ecg/catalog")
async def api_ecg_catalog(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Public catalog of 11 cardiac rhythms. The Per-Patient Console
    (M25) and Nursing Station (M27) both fetch this to populate their
    rhythm pickers + render the SVG strip."""
    return JSONResponse({"catalog": ecg_mod.catalog()})


@app.get("/api/encounter/{encounter_id}/ecg")
async def api_encounter_ecg_get(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Per-encounter ECG state: enabled flag + currently selected
    rhythm id. Read by the Per-Patient Console + Nursing Station."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    return JSONResponse({
        "enabled":     enc.ecg_enabled,
        "rhythm_id":   enc.ecg_rhythm_id,
        "rhythm":      ecg_mod.get(enc.ecg_rhythm_id),
    })


@app.post("/api/encounter/{encounter_id}/ecg")
async def api_encounter_ecg_set(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Instructor sets the encounter's rhythm + ECG-on/off toggle.
    Body: `{"rhythm_id": "afib", "enabled": true}` — either field
    optional. Unknown rhythm_id 400s."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if "rhythm_id" in body:
        rid = str(body["rhythm_id"])
        if not ecg_mod.is_valid_id(rid):
            raise HTTPException(400, f"Unknown rhythm_id {rid!r}.")
        # FR-012 — selecting a waveform ALIGNS the vitals to it (HR from the
        # catalog default_rate + a perfusion crash for arrest rhythms), carrying
        # to the monitor + nurse station. Pass align_vitals=false for rhythm-only;
        # the per-parameter telemetry inject still fine-tunes either way.
        if bool(body.get("align_vitals", True)):
            from portal import physiology
            physiology.apply_rhythm(encounter_id, rid)
        else:
            enc.ecg_rhythm_id = rid
    if "enabled" in body:
        enc.ecg_enabled = bool(body["enabled"])
    return JSONResponse({
        "enabled":     enc.ecg_enabled,
        "rhythm_id":   enc.ecg_rhythm_id,
        "rhythm":      ecg_mod.get(enc.ecg_rhythm_id),
    })


@app.get("/api/vent/state_presets")
async def api_vent_state_presets(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-012 — ventilator clinical-state presets the instructor can select."""
    from portal import vent_state
    return JSONResponse({"presets": vent_state.state_presets()})


@app.post("/api/encounter/{encounter_id}/vent_state")
async def api_encounter_vent_state(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """FR-012 — instructor selects a ventilator clinical state; the vent settings
    + patient condition + vitals all align. Body: ``{"state_id": "ards"}``."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    if encounter_id not in room.encounters:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    from portal import vent_state
    view, err = vent_state.apply_state(encounter_id, str(body.get("state_id", "")))
    if err:
        raise HTTPException(400, err)
    return JSONResponse({"ok": True, "vent": view})


@app.get("/api/control/readiness")
async def api_control_readiness(
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 G2 — system readiness (portal / network / cert / voice / speech /
    storage / EHR / vault / session / devices) for the mission-control readiness
    bar + Setup board. The vault lets the voice check verify stored provider keys."""
    from portal import readiness
    # FR-011 — keep the process-wide Anthropic key cache fresh while the operator
    # console is open. The cache is otherwise populated ONLY by room-start /
    # single-start / credentials-save; a restart + auto-resume restores the room
    # WITHOUT going through start, leaving the cache EMPTY — which made the LAN
    # /api/face/{id}/listen route fall back to ECHO (room encounters carry no
    # stamped api_key, so it had nothing to use). The console polls this every 15s
    # with the vault, so the key self-heals as soon as the operator has it open.
    try:
        _capture_anthropic_key(vault.get("ANTHROPIC_API_KEY") or "")
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(readiness.snapshot(vault))


@app.post("/api/control/readiness/action")
async def api_control_readiness_action(
    request: Request,
    vault: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 G2 — run a one-tap readiness action (resume session / warm speech /
    re-check cert / restart hint / test all); returns the result + a fresh snapshot."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    from portal import readiness
    result = readiness.run_action(str(body.get("id", "")))
    result["readiness"] = readiness.snapshot(vault)
    return JSONResponse(result)


@app.post("/api/control/session/resume")
async def api_control_session_resume(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 G4 — restore the last saved session (the G1 snapshot) on demand, for
    the cockpit's Resume banner. ok=False when there's nothing to resume."""
    from portal import session_state
    summary = session_state.resume()
    return JSONResponse({"ok": bool(summary), "summary": summary})


@app.get("/api/control/operate")
async def api_control_operate(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """FR-011 — LIVE operations layout for the Operate cockpit. Returns one card
    per entity (each bed/patient, every shared character, med carts, nursing
    station) with its join code, live counts, and the focused URL the instructor
    can open in place OR pop out onto another monitor to watch in real time.

    Room-aware: a multi-bed room makes `get_active()` None, which is exactly why
    the old cockpit looked empty after a room launch — here we read the active
    ROOM directly, falling back to a single session, then to nothing."""
    from portal import control_room, control_session, ehr_db, library

    def _dev_count(enc_id: str) -> int:
        try:
            return len(ehr_db.device_stations(enc_id) or [])
        except Exception:  # noqa: BLE001
            return 0

    entities: list = []
    room = control_room.get_active_room()
    if room is not None and room.encounters:
        encs = list(room.encounters.values())
        shared = list(getattr(room, "shared_personas", []) or [])
        for i, enc in enumerate(encs, 1):
            chars = [p for p in (enc.selected_personas or []) if p not in shared]
            _title = enc.encounter_label or enc.scenario_name or f"Bed {i}"
            _sub = enc.scenario_name or ""
            if _sub and _sub in _title:        # label already carries the scenario — no echo
                _sub = ""
            entities.append({
                "kind": "patient",
                "id": enc.id,
                "title": _title,
                "sub": _sub,
                "join": enc.join_code,
                "stats": [f"{_dev_count(enc.id)} device(s)",
                          f"{len(chars)} character(s)"],
                # ?return=console so the encounter console's Back returns to the new
                # Mission Control card pages, not the classic room.
                "open_url": f"/portal/room/encounter/{enc.id}?return=console",
            })
        for pid in shared:
            p = library.get_persona(pid) or {}
            has_voice = any(pid in (e.voice_assignments or {}) for e in encs)
            entities.append({
                "kind": "character",
                "id": pid,
                "title": p.get("name") or pid,
                "sub": "Shared · voice set" if has_voice else "Shared · no voice yet",
                "open_url": f"/portal/room/shared/{pid}",
                "qr_url": f"/qr/face/{pid}.svg?mode=audio",
            })
        for cart_id, beds in (getattr(room, "cart_links", {}) or {}).items():
            # Direct cart UI (same as the classic "🛒 Open cart"): /device/<primary
            # bed join>/<cart id>. Pops out to its own window, not the classic room.
            station = ehr_db.get_device_station(cart_id) or {}
            primary_eid = station.get("session_id") or ((beds or [None])[0])
            primary_enc = room.encounters.get(primary_eid) if primary_eid else None
            cart_url = (f"/device/{primary_enc.join_code}/{cart_id}"
                        if primary_enc else "/portal/room")
            entities.append({
                "kind": "med_cart",
                "id": cart_id,
                "title": (getattr(room, "cart_labels", {}) or {}).get(cart_id, "Med cart"),
                "sub": f"{len(beds or [])} bed(s) linked",
                "open_url": cart_url,
            })
        if len(encs) > 1:
            entities.append({
                "kind": "nursing",
                "id": "nursing",
                "title": "Nursing station",
                "sub": "Shared monitor for the room",
                "open_url": "/portal/control/launch_nurse_station",
            })
        # Medical records (session-wide patient charts) — pops out to its own window.
        entities.append({
            "kind": "ehr",
            "id": "records",
            "title": "Medical records",
            "sub": "Patient charts · MAR · notes · vitals",
            "open_url": "/portal/medical_records",
        })
        return JSONResponse({"ok": True, "mode": "room",
                             "label": room.label or "Care room",
                             # room lifecycle state for the Operate room-controls bar
                             "room_id": room.room_id,
                             "room_code": getattr(room, "room_code", ""),
                             "states": [getattr(e, "state", "") for e in encs],
                             "entities": entities})

    try:
        sess = control_session.get_active()
    except Exception:  # noqa: BLE001
        sess = None
    if sess is not None:
        entities.append({
            "kind": "patient",
            "id": sess.id,
            "title": getattr(sess, "encounter_label", "") or sess.scenario_name or "Patient",
            "sub": sess.scenario_name or "",
            "join": sess.join_code,
            "stats": [f"{_dev_count(sess.id)} device(s)",
                      f"{len(sess.selected_personas or [])} character(s)"],
            "open_url": "/portal/control",
        })
        for pid in (sess.selected_personas or []):
            p = library.get_persona(pid) or {}
            if (p.get("roleGroup") or "") == "Patient":
                continue
            has_voice = pid in (getattr(sess, "voice_assignments", {}) or {})
            entities.append({
                "kind": "character",
                "id": pid,
                "title": p.get("name") or pid,
                "sub": "voice set" if has_voice else "no voice yet",
                "open_url": "/portal/control",
                "qr_url": f"/qr/face/{pid}.svg?mode=audio&scenario={sess.id}",
            })
        return JSONResponse({"ok": True, "mode": "single",
                             "label": sess.scenario_name or "Session", "entities": entities})

    return JSONResponse({"ok": True, "mode": "none", "label": "", "entities": []})


# =====================================================================
# V7 M30 — Per-encounter parity (transcript / voice / lead student)
# =====================================================================

@app.get("/api/encounter/{encounter_id}/transcript")
async def api_encounter_transcript(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    limit: int = 50,
):
    """Latest N transcript entries for one encounter (newest last,
    matching the v6 chat-station log convention). Polled by the
    Per-Patient Console's transcript card."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    n = max(1, min(limit, 500))
    rows = enc.transcript[-n:]
    return JSONResponse({
        "encounter_id": enc.id,
        "transcript": [
            {
                "ts":            t.ts,
                "source":        t.source,
                "source_label":  t.source_label,
                "persona_id":    t.persona_id,
                "persona_name":  t.persona_name,
                "direction":     t.direction,
                "text":          t.text,
                "latency_ms":    t.latency_ms,
            }
            for t in rows
        ],
        "total_entries": len(enc.transcript),
    })


@app.get("/api/encounter/{encounter_id}/voices")
async def api_encounter_voices_get(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Per-encounter voice assignments — persona_id → voice_id.
    Empty when no voices configured (browser TTS fallback).

    M33 — Also returns a `personas` array carrying each persona's
    display `name` + `role` so the Per-Patient Console voice picker
    can label rows by character name instead of raw persona ID, and
    a `join_code` so the per-row "Engage" buttons can deep-link to
    the chat join page. `selected_personas` is preserved for
    backward-compat callers.
    """
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    # M33 — Hydrate persona id → {id, name, role}. If a persona id is
    # in selected_personas but missing from the library (shouldn't
    # happen in practice, but defensive), echo back the id as both
    # id and name so the UI still has something to render.
    personas_full: list[dict[str, str]] = []
    for pid in enc.selected_personas:
        p = library.get_persona(pid)
        if p is None:
            personas_full.append({"id": pid, "name": pid, "role": ""})
        else:
            personas_full.append({
                "id":   p.get("id", pid),
                "name": p.get("name", pid),
                "role": p.get("role", ""),
            })
    return JSONResponse({
        "encounter_id":       enc.id,
        "selected_personas":  list(enc.selected_personas),
        "patient_persona_id": enc.patient_persona_id,
        "voice_assignments":  dict(enc.voice_assignments),
        "personas":           personas_full,
        "join_code":          enc.join_code,
    })


@app.post("/api/encounter/{encounter_id}/voices")
async def api_encounter_voices_set(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Operator sets/clears one or more persona voice assignments.
    Body: `{"P-001": "voice_id_xxx", "P-013": null}` — null clears
    the entry (browser-TTS fallback for that persona)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be {persona_id: voice_id|null}.")
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    for persona_id, voice_id in body.items():
        if voice_id is None or voice_id == "":
            enc.voice_assignments.pop(persona_id, None)
        else:
            enc.voice_assignments[persona_id] = str(voice_id)
    return JSONResponse({
        "ok": True,
        "voice_assignments": dict(enc.voice_assignments),
    })


@app.get("/api/encounter/{encounter_id}/lead_student")
async def api_encounter_lead_student_get(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Read the encounter's lead student id (or null) + a roster
    list the picker uses."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    lead_name = None
    if enc.lead_student_id and enc.lead_student_id in room.students:
        lead_name = room.students[enc.lead_student_id].display_name
    return JSONResponse({
        "encounter_id":      enc.id,
        "lead_student_id":   enc.lead_student_id,
        "lead_student_name": lead_name,
        "roster": [
            {"student_id":   s.student_id,
             "display_name": s.display_name,
             "role":         s.role,
             "assigned_to_this": s.assigned_encounter_id == enc.id}
            for s in room.students.values()
            if s.role == "bedside"   # nurse_station students never lead a bed
        ],
    })


@app.post("/api/encounter/{encounter_id}/lead_student")
async def api_encounter_lead_student_set(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Set or clear the encounter's lead student. Body:
        {"lead_student_id": "stu_xxx" | null}
    Setting to null clears the lead. The student_id must exist on
    the room's roster (unless null)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    sid = body.get("lead_student_id")
    if sid in (None, "", "null"):
        enc.lead_student_id = None
    else:
        sid = str(sid)
        if sid not in room.students:
            raise HTTPException(404,
                f"Unknown student {sid!r} for this room.")
        enc.lead_student_id = sid
    lead_name = None
    if enc.lead_student_id:
        lead_name = room.students[enc.lead_student_id].display_name
    return JSONResponse({
        "ok": True,
        "encounter_id":      enc.id,
        "lead_student_id":   enc.lead_student_id,
        "lead_student_name": lead_name,
    })


# =====================================================================
# V7 M53 — Lead-label assignments (free-text name / group / list).
#
# A parallel API to the M30 roster-picked lead. Lets the instructor
# type any string ("Team Alpha", "Alice, Bob, Charlie", "Alice Pham")
# and apply it to one OR many encounters at once from the Multi-
# Patient Control dashboard.
#
# Distinct from /api/encounter/{eid}/lead_student because the M30 API
# requires the lead to be a student already on the roster. M53 lets
# the operator label leads who haven't joined yet, or use a group
# name when no single student "owns" the bed at debrief time.
#
# Stored as a plain string field on the Encounter dataclass. Empty
# string == no label set (the GET response surfaces lead_label="").
# =====================================================================

@app.get("/api/room/lead_assignments")
async def api_room_lead_assignments_get(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Read every encounter's current lead label + roster fallback.
    Powers the Multi-Patient Control "👤 Lead assignments" panel."""
    room = _require_active_room()
    rows = []
    for enc in room.encounters.values():
        label = (getattr(enc, "lead_label", "") or "").strip()
        fallback_name = None
        if enc.lead_student_id and enc.lead_student_id in room.students:
            fallback_name = room.students[enc.lead_student_id].display_name
        rows.append({
            "encounter_id":     enc.id,
            "encounter_label":  enc.encounter_label or enc.scenario_name,
            "lead_label":       label,
            "lead_student_id":  enc.lead_student_id,
            "lead_student_name": fallback_name,
            "effective_lead_display": label or fallback_name or "",
        })
    return JSONResponse({"encounters": rows})


@app.post("/api/encounter/{encounter_id}/lead_label")
async def api_encounter_lead_label_set(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Set or clear ONE encounter's free-text lead label. Body:
        {"lead_label": "Team Alpha"}
    or
        {"lead_label": ""}   # clears
    Whitespace is trimmed. There is no length cap or character
    restriction — the instructor's words are the source of truth."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    label = str(body.get("lead_label") or "").strip()
    enc.lead_label = label
    return JSONResponse({
        "ok": True,
        "encounter_id": enc.id,
        "lead_label":   enc.lead_label,
    })


@app.post("/api/room/lead_assignments")
async def api_room_lead_assignments_bulk(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Apply one or more lead-label assignments in a single call.

    Body:
        {"assignments": [
            {"encounter_ids": ["enc_1","enc_2"], "lead_label": "Team Alpha"},
            {"encounter_ids": ["enc_3"],        "lead_label": "Alice"},
            ...
        ]}

    Each assignment writes the same `lead_label` to every listed
    encounter. Unknown encounter ids are skipped (returned in the
    response's `unknown` list so the UI can warn the operator).

    Passing `lead_label: ""` clears the label for the listed beds —
    same as POSTing the single-encounter endpoint with empty text."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    assignments = body.get("assignments") or []
    if not isinstance(assignments, list):
        raise HTTPException(400, "assignments must be a list.")
    applied: list[dict[str, Any]] = []
    unknown: list[str] = []
    for entry in assignments:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("lead_label") or "").strip()
        eids = entry.get("encounter_ids") or []
        if not isinstance(eids, list):
            continue
        for eid in eids:
            sid = str(eid)
            enc = room.encounters.get(sid)
            if enc is None:
                unknown.append(sid)
                continue
            enc.lead_label = label
            applied.append({"encounter_id": enc.id, "lead_label": label})
    return JSONResponse({
        "ok": True,
        "applied": applied,
        "unknown": unknown,
    })


# =====================================================================
# V7 M55 — Per-encounter medications card + active-at-start toggles.
#
# Each encounter's personas have a seed-derived MAR (built by
# ehr_seed.seeds_for_all_personas). The instructor can mark a subset
# of those meds "active at start" from the Per-Patient Console's
# 💊 Medications card; the med cart (M47) then filters its display
# to only the active meds per patient.
#
# Default semantics: when an encounter has NO active list for a
# persona, the cart shows every med (back-compat with pre-M55 carts).
# Once the operator interacts (POSTs a list, even an empty one), the
# explicit list wins.
# =====================================================================

@app.get("/api/encounter/{encounter_id}/medications")
async def api_encounter_medications_get(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Return every persona's seed-derived MAR + which meds the
    instructor has flagged active at start.

    Response shape:
        {"encounter_id": "...",
         "personas": [
           {"character_id": "P-014", "name": "Jane Doe",
            "explicit_active_list": true|false,
            "medications": [
              {"name": "Furosemide", "dose": "40 mg",
               "route": "IV", "frequency": "q6h",
               "high_alert": false, "med_id": "med_furosemide_001",
               "active": true},
              ...
            ]}, ...]}

    `explicit_active_list` is False when the operator hasn't
    interacted yet — every `active` field is True (default-all). Once
    the operator POSTs a list, becomes True; only listed meds carry
    `active=True`.
    """
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    from portal import ehr_seed as _ehr_seed
    # M58 — Operator: "Med list should only populate with Patient
    # character medications no other character." Family / clinician
    # personas in selected_personas have no MAR; iterating over them
    # was producing empty (or noisy stub) med rows. Filter to the
    # patient persona only.
    per_persona = _ehr_seed.seeds_for_patient_only(
        enc, ehr_id=enc.ehr_id) or []
    out: list[dict[str, Any]] = []
    active_map = getattr(enc, "active_medications", {}) or {}
    for p in per_persona:
        pid = p.get("character_id") or ""
        explicit = pid in active_map
        active_names_lower = {
            (n or "").strip().lower()
            for n in (active_map.get(pid) or [])
        }
        meds_out: list[dict[str, Any]] = []
        for m in (p.get("medications") or []):
            name = (m.get("name") or "").strip()
            if explicit:
                is_active = name.lower() in active_names_lower
            else:
                is_active = True   # default-all
            meds_out.append({
                "med_id":      m.get("med_id") or "",
                "name":        name,
                "dose":        m.get("dose") or "",
                "route":       m.get("route") or "",
                "frequency":   m.get("frequency") or "",
                "high_alert":  bool(m.get("high_alert")),
                "rationale":   m.get("rationale") or "",
                "active":      is_active,
            })
        out.append({
            "character_id":          pid,
            "name":                  p.get("name") or pid,
            "explicit_active_list":  explicit,
            "medications":           meds_out,
        })
    return JSONResponse({"encounter_id": enc.id, "personas": out})


@app.post("/api/encounter/{encounter_id}/medications/active")
async def api_encounter_medications_active_set(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Replace one persona's active-meds list. Body:
        {"persona_id": "P-014",
         "active_med_names": ["Furosemide", "Lisinopril"]}

    Passing an empty list explicitly sets "no meds active for this
    patient at start". To restore the default (show every med),
    omit the persona_id from active_medications via DELETE below.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    pid = (body.get("persona_id") or "").strip()
    if not pid:
        raise HTTPException(400, "persona_id required.")
    names = body.get("active_med_names") or []
    if not isinstance(names, list):
        raise HTTPException(400, "active_med_names must be a list.")
    if not hasattr(enc, "active_medications") or enc.active_medications is None:
        enc.active_medications = {}
    enc.active_medications[pid] = [
        str(n).strip().lower() for n in names if str(n).strip()
    ]
    return JSONResponse({
        "ok":            True,
        "encounter_id":  enc.id,
        "persona_id":    pid,
        "active_count":  len(enc.active_medications[pid]),
    })


@app.delete("/api/encounter/{encounter_id}/medications/active/{persona_id}")
async def api_encounter_medications_active_clear(
    encounter_id: str,
    persona_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Reset one persona to default behaviour (every med shows on the
    cart). The DELETE just removes the entry; the GET response then
    reports `explicit_active_list=False` again."""
    room = _require_active_room()
    enc = room.encounters.get(encounter_id)
    if enc is None:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if hasattr(enc, "active_medications") and enc.active_medications:
        enc.active_medications.pop(persona_id, None)
    return JSONResponse({
        "ok":            True,
        "encounter_id":  enc.id,
        "persona_id":    persona_id,
    })


# =====================================================================
# V7 Phase 7 — Telemetry simulation (M23)
# =====================================================================

@app.get("/api/encounter/{encounter_id}/telemetry")
async def api_encounter_telemetry(
    encounter_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    jitter: bool = True,
):
    """Snapshot the encounter's live telemetry. M23 derives from the
    latest vitals.record (or default values) + optional small jitter.
    Polled by M25 Per-Patient Console (1s cadence) and M27 Nursing
    Station mini-strips (2s cadence)."""
    room = _require_active_room()
    if encounter_id not in room.encounters:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    return JSONResponse(telemetry_mod.snapshot(encounter_id, jitter=jitter))


@app.post("/api/encounter/{encounter_id}/telemetry/override")
async def api_encounter_telemetry_override(
    encounter_id: str,
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Instructor force-set one or more telemetry metrics. Body:
        {"hr": 132, "sbp": 70}                 — set
        {"clear": "hr"}                         — clear one
        {"clear_all": true}                     — clear every override
    Returns the post-update override dict."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    if encounter_id not in room.encounters:
        raise HTTPException(404, f"Unknown encounter {encounter_id!r}.")
    if body.get("clear_all"):
        telemetry_mod.clear_all_overrides(encounter_id)
        return JSONResponse({"ok": True, "overrides": {}})
    if "clear" in body:
        key = str(body["clear"])
        try:
            updated = telemetry_mod.clear_override(encounter_id, key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return JSONResponse({"ok": True, "overrides": updated})
    updated = telemetry_mod._load_overrides(encounter_id)
    for key, value in body.items():
        if key in telemetry_mod._VALID_METRICS:
            try:
                updated = telemetry_mod.set_override(encounter_id, key, value)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
    return JSONResponse({"ok": True, "overrides": updated})


# =====================================================================
# V7 — Per-encounter cost caps (M17)
# =====================================================================

@app.get("/api/room/budget")
async def api_room_budget(
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Operator-facing snapshot of the active room's cost-cap usage."""
    room = _require_active_room()
    return JSONResponse(room.budget.usage())


@app.post("/api/room/budget")
async def api_room_budget_set(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_instructor)],
):
    """Update the active room's caps. Body JSON (any subset):
        {"haiku_rate_cap": <int|null>,  "voice_char_cap": <int|null>}
    Pass null to clear a cap. Returns the new usage snapshot."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required.") from None
    room = _require_active_room()
    if "haiku_rate_cap" in body:
        v = body["haiku_rate_cap"]
        room.haiku_rate_cap = int(v) if v is not None else None
    if "voice_char_cap" in body:
        v = body["voice_char_cap"]
        room.voice_char_cap = int(v) if v is not None else None
    # Touch the property so the tracker picks up the new values.
    return JSONResponse(room.budget.usage())


@app.websocket("/ws/room/{room_code}")
async def ws_room_channel(ws: WebSocket, room_code: str) -> None:
    """M16 — Per-room broadcast channel. Stations subscribe on page
    load and react to freeze / resume / scene / end events in real
    time. No auth on the WS upgrade — the room_code itself is the
    access token (matches the v6 chat-station / device-station
    pattern). Closed sockets are pruned on the next broadcast."""
    await ws_room.handle_room_ws(ws, room_code)


@app.get("/portal/cohort-debriefs", response_class=HTMLResponse)
async def portal_cohort_debrief_index(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Index page listing every saved cohort debrief, newest first.

    Path is `/portal/cohort-debriefs` (plural, top-level) to avoid
    conflicting with the v6 `/portal/debrief/{session_id}` route
    (which would have caught `/portal/debrief/cohort` as a session
    id lookup).
    """
    return templates.TemplateResponse(
        request, "debrief_cohort_index.html",
        {"active": "debrief", "cohorts": debrief_mod.list_saved_cohorts()},
    )


# ----- VRAI Faces tablet launcher (v8) -----------------------------------
# Memory_management.MD §6 — the QR encodes the LAN URL of the vrai-faces
# dev/preview server; the tablet camera scans it and the avatar boots
# full-screen, bound to <character_id>.

import os as _os                  # local, only this section uses it
import shutil as _shutil          # local — locate pnpm for dev-server autostart
import subprocess as _subprocess  # local — spawn the vite dev server on demand
from urllib.parse import quote as _quote, urlsplit as _urlsplit  # local, this section

# Handle to the vite dev server the portal auto-starts when an instructor clicks
# "Develop avatar" and the app isn't already running. Idempotent: we re-probe
# the port before spawning, so a lost handle (portal restart) or a manually
# started server is handled gracefully.
_vrai_dev_proc: "_subprocess.Popen[bytes] | None" = None


def _vrai_base(request: Request) -> str:
    """The scheme://host:port the VRAI Faces app is served at — VRAI_FACES_BASE_URL
    if set, else derived from the portal's own host + VRAI_FACES_VITE_PORT (5173)."""
    base = _os.environ.get("VRAI_FACES_BASE_URL")
    if not base:
        host = request.url.hostname or "localhost"
        port = int(_os.environ.get("VRAI_FACES_VITE_PORT", "5173"))
        base = f"{request.url.scheme or 'http'}://{host}:{port}"
    return base.rstrip("/")


def _vrai_base_for_qr(request: Request) -> str:
    """Like _vrai_base, but LAN-reachable for a *scanned* QR: a request-derived
    localhost / 127.0.0.1 host is swapped for the detected LAN IP so the page
    opens on another device. A configured VRAI_FACES_BASE_URL is returned as-is
    (the operator's explicit choice)."""
    base = _os.environ.get("VRAI_FACES_BASE_URL")
    if base:
        return base.rstrip("/")
    host = _public_host() or (request.url.hostname or "localhost")
    if host in ("127.0.0.1", "localhost", "::1", ""):
        host = _lan_ip()
    port = int(_os.environ.get("VRAI_FACES_VITE_PORT", "5173"))
    return f"{request.url.scheme or 'http'}://{host}:{port}"


def _vrai_faces_url(
    request: Request,
    character_id: str,
    *,
    scenario_id: str,
    opacity: float,
    lan: bool = False,
    debug: bool = False,
    mode: str = "",
) -> str:
    """Build the URL to the vrai-faces shell for this tablet.

    Dev: VRAI_FACES_BASE_URL=http://<host>:5173  (vite dev)
    Preview: VRAI_FACES_BASE_URL=http://<host>:4173  (vite preview)
    Prod: VRAI_FACES_BASE_URL=<absolute prefix where dist/ is served>

    If the env var is unset, the URL is derived from the portal's own
    request hostname plus port 5173.

    `lan=True` (QR / tablet-pairing): the app host AND the embedded `api`
    portal origin are made LAN-reachable — a request-derived 127.0.0.1 /
    localhost is swapped for the detected LAN IP. Without this, a QR scanned
    on a *different* device points the bind fetch and the speech WebSocket at
    that device's own localhost (ws://127.0.0.1/…) → connection refused.
    `lan=False` (develop, on the operator's own box) keeps localhost so the
    autostart path can manage the local dev server.
    """
    safe_char = character_id.strip()
    safe_scen = scenario_id.strip() or "default"
    op = max(0.0, min(1.0, opacity))
    # Carry the portal origin so the avatar can call back for its bind payload
    # (portrait + speech WS URL) — GET {api}/api/face/{char}/binding (Phase 4.3).
    # The speech WS URL is derived (server-side) from whatever host the app used
    # here, so making `api` LAN-reachable also makes the WebSocket LAN-reachable.
    portal_origin = _base_url_for_qr(request) if lan else str(request.base_url).rstrip("/")
    if _portal_serves_app():
        # Durable device mode (ADR-0028): the portal IS the app host, so the app
        # base and the `api` origin are one and the same — every fetch + the
        # speech WS is same-origin (one cert, no cross-origin, no vite :5173).
        app_base = portal_origin
    else:
        app_base = _vrai_base_for_qr(request) if lan else _vrai_base(request)
    api = _quote(portal_origin, safe="")
    url = (f"{app_base}/face/{safe_char}"
           f"?scenario={safe_scen}&opacity={op:.2f}&api={api}")
    # ADR-0027 device token (opt-in, MEDSIM_FACE_TOKEN): a per-(scenario,character)
    # capability the device echoes back on /listen. LAN/QR URLs only.
    if lan and vrai_faces.token_enabled():
        url += f"&token={vrai_faces.face_token(safe_scen, safe_char)}"
    if debug:
        url += "&debug=1"   # 🐞 on-screen console + morph-QA panel + translucency slider (RB-003)
    if mode == "audio":
        # FR-006 — audio-only station (low-cost tablets): the app shows a flat static
        # portrait + voice loop, no 3D rig / WebGPU. (Inert until the lite mode ships;
        # QRs minted now stay correct.)
        url += "&mode=audio"
    return url


@app.get("/qr/face/{character_id}.svg")
async def vrai_face_qr(
    request: Request,
    character_id: str,
    scenario: str = "default",
    opacity: float = 0.66,
    scale: int = 8,
    debug: int = 0,
    mode: str = "",
):
    """SVG QR code that, when scanned on a tablet, opens the full-screen
    VRAI Faces avatar bound to <character_id>. No auth — facilitators
    print/show these on the control room screen. `debug=1` opens the build
    with the on-screen console + morph-QA panel (RB-003 QA). `mode=audio`
    (FR-006) marks an audio-only station — flat portrait + voice, no 3D rig."""
    # lan=True: a scanned QR opens on a *different* device, so the app host +
    # the embedded portal `api` (→ bind fetch + speech WebSocket) must be the
    # LAN IP, never 127.0.0.1 (which would resolve to the tablet itself).
    url = _vrai_faces_url(request, character_id, scenario_id=scenario, opacity=opacity,
                          lan=True, debug=bool(debug),
                          mode=("audio" if mode == "audio" else ""))
    svg = qrgen.make_qr_svg(url, scale=scale)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/rootca.pem")
async def vrai_rootca():  # noqa: ANN202
    """Serve the dev CA so a tablet can install + trust it (ADR-0027 HTTPS) without
    emailing files around. Open this URL on the device (proceed past the one-time
    warning), then install the downloaded cert as a CA. No auth — it's the PUBLIC
    CA certificate (the thing you install); the private key never leaves the Mac.
    The x-x509-ca-cert type makes Android offer the CA-install flow directly."""
    ca = PORTAL_DIR / "data" / "certs" / "rootCA.pem"
    if not ca.is_file():
        return JSONResponse(
            {"ok": False, "error": "no dev CA — run scripts/make-dev-cert.sh first"},
            status_code=404,
        )
    return Response(
        content=ca.read_bytes(),
        media_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": 'attachment; filename="medsim-dev-ca.crt"'},
    )


@app.get("/onboard")
async def vrai_onboard(request: Request):  # noqa: ANN202
    """HTTPS tablet-onboarding page (runbook §3b). The plain-HTTP helper on :8766
    is unreachable from Android Chrome (HTTPS-First upgrades hand-typed http://
    URLs), so Androids land HERE instead: scan the QR → proceed past the one-time
    cert warning → /onboard → download the CA → install. No auth — instructions
    + the public CA only."""
    host = (request.headers.get("host") or "").split(":")[0] or "localhost"
    portal = f"https://{host}:{request.url.port or 8765}"
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MedSim — connect this tablet</title>
<style>body{{font-family:-apple-system,Roboto,Helvetica,Arial,sans-serif;background:#0a234f;
color:#fff;margin:0;padding:28px 20px;line-height:1.5}}h1{{font-size:22px;margin:0 0 4px}}
.sub{{color:#a8c0f0;font-size:14px;margin-bottom:18px}}.card{{background:#102f6b;border-radius:12px;
padding:16px 18px;margin:14px 0}}h2{{font-size:16px;margin:0 0 8px}}ol{{margin:0;padding-left:20px}}
li{{margin:7px 0;font-size:15px}}a.btn{{display:inline-block;background:#2f7d5b;color:#fff;
text-decoration:none;padding:13px 22px;border-radius:9px;font-weight:700;margin:10px 0}}
.note{{font-size:13px;color:#a8c0f0}}</style></head><body>
<h1>Connect this tablet to MedSim</h1>
<div class="sub">One-time setup: trust the room's certificate, then every scan just works.</div>
<div class="card"><h2>1 · Download the certificate</h2>
<a class="btn" href="/rootca.pem">⬇ Download room certificate</a>
<div class="note">If a warning appears, choose Download/Keep — this is the room's own certificate.</div></div>
<div class="card"><h2>2 · Install it</h2><ol>
<li><b>Android:</b> Settings → Security &amp; privacy → More security → Encryption &amp; credentials →
<b>Install a certificate → CA certificate</b> → choose the downloaded file.</li>
<li><b>iPad:</b> Settings → <b>Profile Downloaded</b> → Install; then Settings → General → About →
Certificate Trust Settings → switch the MedSim certificate <b>on</b>.</li></ol></div>
<div class="card"><h2>3 · Done — open MedSim</h2>
<a class="btn" style="background:#143b8a" href="{portal}">Open MedSim</a>
<div class="note">Or just re-scan the QR the instructor shows you.</div></div>
</body></html>"""
    return HTMLResponse(content=html)


def _vrai_app_reachable(url: str, timeout: float = 0.4) -> bool:
    """Quick TCP probe of the VRAI Faces app host:port. A local refused
    connection returns at once; only a truly unreachable remote host waits out
    the (short) timeout."""
    try:
        parts = _urlsplit(url)
        host = parts.hostname or "localhost"
        port = parts.port or (443 if parts.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_node_tool(name: str) -> str | None:
    """Locate a node-toolchain binary (pnpm/node) even when the portal was
    launched without the toolchain on PATH (the common case — a GUI/service
    launch doesn't inherit a login shell's PATH). Checks PATH first, then the
    usual install dirs (pnpm standalone, Homebrew, nvm/volta/asdf, and the
    `~/.local/node/current/bin` layout this project uses)."""
    found = _shutil.which(name)
    if found:
        return found
    import glob as _glob
    home = _os.path.expanduser("~")
    candidates = [
        f"{home}/.local/node/current/bin/{name}",
        f"{home}/.local/share/pnpm/{name}",
        f"{home}/Library/pnpm/{name}",
        "/opt/homebrew/bin/" + name,
        "/usr/local/bin/" + name,
        f"{home}/.volta/bin/{name}",
        f"{home}/.asdf/shims/{name}",
        *sorted(_glob.glob(f"{home}/.nvm/versions/node/*/bin/{name}"), reverse=True),
    ]
    for c in candidates:
        if _os.path.isfile(c) and _os.access(c, _os.X_OK):
            return c
    return None


def _ensure_vrai_dev_server(base: str) -> tuple[str, str | None]:
    """Start the vite dev server if it isn't already running. Returns
    (status, error) where status ∈ {"already", "spawned", "error"}. Only ever
    starts a LOCAL server; the command is fixed — no user input reaches a shell
    (list args, no shell=True). Detached so it survives this request; idempotent
    via the port probe + the live handle. Falls back to running vite directly
    with node when pnpm can't be located."""
    global _vrai_dev_proc
    if _vrai_dev_proc is not None and _vrai_dev_proc.poll() is None:
        return "already", None
    vrai_dir = PORTAL_DIR.parent / "vrai-faces"
    if not (vrai_dir / "pnpm-workspace.yaml").is_file():
        return "error", f"vrai-faces workspace not found at {vrai_dir}"

    port = _urlsplit(base).port or 5173
    vite_args = ["--port", str(port), "--strictPort", "--host"]
    node = _find_node_tool("node")
    pnpm = _find_node_tool("pnpm")
    core_dir = vrai_dir / "packages" / "core"
    vite_js = core_dir / "node_modules" / "vite" / "bin" / "vite.js"
    # PREVIEW mode (opt-in, VRAI_FACES_SERVE=preview): build + serve the
    # production bundle so the device gets the real app-shell cache + installable
    # PWA (the dev server serves /src, not the hashed /assets the SW caches).
    # Default stays the dev server (HMR) for avatar development — unchanged path.
    serve_mode = (_os.environ.get("VRAI_FACES_SERVE") or "dev").strip().lower()
    serve_preview_js = core_dir / "scripts" / "serve-preview.mjs"

    if serve_mode == "preview" and node and serve_preview_js.is_file():
        # Build-then-preview via the vite JS API (one node process; first start
        # pays the ~5–15 s build, then serves dist over preview on `port`).
        cmd: list[str] = [node, str(serve_preview_js), str(port)]
        cwd = core_dir
        node_dir = _os.path.dirname(node)
    elif node and vite_js.is_file():
        # Preferred (dev): run vite directly. Args go straight to vite
        # (deterministic port binding) and it needs only node, not pnpm.
        cmd = [node, str(vite_js), *vite_args]
        cwd = core_dir
        node_dir = _os.path.dirname(node)
    elif pnpm:
        # Fallback: pnpm runs the `dev` script. NO `--` — pnpm forwards trailing
        # args to the script verbatim, so a `--` reaches vite literally and
        # breaks flag parsing (vite ignores --port and falls back to 5173).
        cmd = [pnpm, "-F", "@vrai/core", "dev", *vite_args]
        cwd = vrai_dir
        node_dir = _os.path.dirname(pnpm)
    else:
        return "error", ("couldn't find node+vite or pnpm (looked on PATH + the "
                         "usual install dirs). Run `pnpm install` in vrai-faces, "
                         "or launch the portal from a shell with node on PATH")

    # Make sure pnpm's / vite's own child processes (node, esbuild) resolve even
    # if the portal's PATH lacks the toolchain.
    env = dict(_os.environ)
    if node_dir:
        env["PATH"] = node_dir + _os.pathsep + env.get("PATH", "")
    try:
        log_path = PORTAL_DIR.parent / "data" / "vrai-dev.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "ab")  # noqa: SIM115 — handed to the child process
        _vrai_dev_proc = _subprocess.Popen(
            cmd, cwd=str(cwd), env=env,
            stdout=log, stderr=_subprocess.STDOUT, stdin=_subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return "error", str(exc)
    return "spawned", None


def _ensure_vrai_app_for_qr(request: Request) -> None:
    """Best-effort: bring up the LAN-reachable vite dev server before we hand a
    device QR to a tablet, so a scan doesn't hit ERR_CONNECTION_REFUSED on the
    app port. The tablet loads the app host directly — it never touches the
    portal's autostart — so the portal must start it when it shows the QR.
    Local-managed only (a configured VRAI_FACES_BASE_URL is the operator's to
    run); idempotent via a reachability probe; never raises (a QR page must not
    500 on autostart). The first call cold-starts vite (~seconds), so give it a
    moment before scanning; reloading the tablet page then succeeds."""
    try:
        if _portal_serves_app():
            return  # durable mode (ADR-0028): the portal serves the app — no vite
        if _os.environ.get("VRAI_FACES_BASE_URL"):
            return
        base = _vrai_base_for_qr(request)
        if not _vrai_app_reachable(base):
            _ensure_vrai_dev_server(base)
    except Exception:  # noqa: BLE001
        pass


@app.get("/portal/face/dev-status")
async def vrai_face_dev_status(
    request: Request,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
):
    """Polled by the 'starting…' page — reports whether the avatar app is up."""
    return JSONResponse({"up": _vrai_app_reachable(_vrai_base(request))})


_VRAI_DEV_STYLE = (
    "body{font-family:-apple-system,system-ui,sans-serif;background:#0b0f1a;"
    "color:#e9edf5;margin:0;padding:40px;line-height:1.5}"
    ".card{max-width:640px;margin:0 auto;background:#121829;border:1px solid #243049;"
    "border-radius:12px;padding:28px 32px}"
    "h1{font-size:20px;font-weight:600;margin:0 0 12px}"
    "code,pre{background:#1c2333;border-radius:6px}"
    "code{padding:2px 6px;font-size:13px;word-break:break-all}"
    "pre{padding:12px 14px;overflow:auto;font-size:13px}"
    ".muted{color:#9aa6c0;font-size:13px}a{color:#8ab4ff}"
    "a.btn{display:inline-block;margin-top:8px;padding:8px 16px;background:#2a3550;"
    "color:#e9edf5;border-radius:8px;text-decoration:none}"
    ".spinner{width:28px;height:28px;border:3px solid #243049;border-top-color:#8ab4ff;"
    "border-radius:50%;animation:spin .8s linear infinite;margin:8px 0 4px}"
    "@keyframes spin{to{transform:rotate(360deg)}}"
)


@app.get("/portal/face/develop/{character_id}")
async def vrai_face_develop(
    request: Request,
    character_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    scenario: str = "default",
    opacity: float = 0.66,
):
    """Open the live avatar in the VRAI Faces app — the 'developer' surface. If
    the app is up, redirect straight in. If not, for a LOCAL app the portal
    auto-starts the vite dev server and shows a 'starting…' page that opens the
    avatar as soon as it's ready (no commands for the instructor). Pairing a
    tablet (the QR) happens later, at assign-for-use time."""
    url = _vrai_faces_url(request, character_id, scenario_id=scenario, opacity=opacity)
    base = _vrai_base(request)
    if _vrai_app_reachable(base):
        return RedirectResponse(url, status_code=302)

    # Only auto-start a LOCAL server we manage. A configured VRAI_FACES_BASE_URL
    # (possibly remote) is the operator's to run.
    host = (_urlsplit(base).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") and not _os.environ.get("VRAI_FACES_BASE_URL"):
        status, err = _ensure_vrai_dev_server(base)
    else:
        status, err = "error", (
            "the avatar app is configured at a remote address "
            "(VRAI_FACES_BASE_URL); start it on that host")

    safe_url = url.replace("&", "&amp;")
    retry = (f"/portal/face/develop/{_quote(character_id)}"
             f"?scenario={_quote(scenario)}&amp;opacity={opacity:.2f}")

    if status == "error":
        inner = (
            "<h1>🪞 Avatar app isn't running</h1>"
            f"<p>Couldn't start it automatically: <code>{err}</code></p>"
            "<p>Start it manually (from <code>vrai-faces/</code>):</p>"
            "<pre>pnpm -F @vrai/core dev</pre>"
            f'<p><a class="btn" href="{retry}">↻ Open developer</a></p>'
            f'<p class="muted">Target: <code>{safe_url}</code></p>')
        script = ""
        code = 503
    else:
        verb = "Starting" if status == "spawned" else "Opening"
        inner = (
            f"<h1>🪞 {verb} the avatar developer…</h1>"
            '<div class="spinner"></div>'
            "<p class=\"muted\">First launch compiles the app — usually a few seconds, "
            f"up to ~20s cold. <code>{character_id}</code> opens here automatically "
            "when it's ready.</p>"
            f'<p id="slow" class="muted" style="display:none">Still working — you can '
            f'<a href="{retry}">retry</a>. Target <code>{safe_url}</code>.</p>')
        script = (
            "<script>\n"
            "  const TARGET = " + json.dumps(url) + ";\n"
            "  const STATUS = " + json.dumps('/portal/face/dev-status') + ";\n"
            "  let n = 0;\n"
            "  function again(){ if(++n===8){var s=document.getElementById('slow');"
            "if(s)s.style.display='block';} if(n<60) setTimeout(poll,1000); }\n"
            "  function poll(){ fetch(STATUS,{cache:'no-store'})"
            ".then(function(r){return r.json();})"
            ".then(function(j){ if(j&&j.up){location.replace(TARGET);return;} again(); })"
            ".catch(again); }\n"
            "  poll();\n"
            "</script>")
        code = 202

    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        "<title>VRAI Faces · developer</title><style>" + _VRAI_DEV_STYLE + "</style>"
        '</head><body><div class="card">' + inner + "</div>" + script + "</body></html>")
    return HTMLResponse(html, status_code=code)


@app.get("/portal/face/launch/{character_id}", response_class=HTMLResponse)
async def vrai_face_launcher(
    request: Request,
    character_id: str,
    _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    scenario: str = "default",
    opacity: float = 0.66,
    debug: int = 0,
):
    """Tablet-pairing page (assign-for-use): shows the resolved name/role, the
    portrait status (custom vs placeholder), and the QR + URL a tablet scans to
    open this avatar. Reached from the ops view for avatar-enabled personas —
    NOT from the Develop button (that opens the live app). Works for both
    character cards and persona ids (P-0xx) via vrai_faces.resolve_card()."""
    info = vrai_faces.launch_info(character_id)
    # The whole point of this page is to hand a tablet the QR — make sure the
    # avatar app is up + LAN-reachable first, so the scan doesn't refuse-connect.
    _ensure_vrai_app_for_qr(request)
    # lan=True: this is the tablet-pairing page — both the QR and the URL it
    # prints must be LAN-reachable (see _vrai_faces_url), so the scanned tablet
    # can reach the portal's bind + speech WebSocket rather than its own host.
    dbg = bool(debug)
    # FR-006 — the launcher must honor the character's station mode. Resolve it from
    # the active session's avatar opt-ins; with no session (standalone launch), the
    # policy default applies: Patient personas → avatar, everyone else → audio-only.
    sess = control_session.get_active()
    if sess is not None and character_id in (sess.selected_personas or []):
        is_avatar = character_id in (sess.avatar_personas or [])
    else:
        _persona = library.get_persona(character_id)
        is_avatar = ((_persona or {}).get("roleGroup") == "Patient"
                     if _persona is not None else True)
    station_mode = "" if is_avatar else "audio"
    url = _vrai_faces_url(request, character_id, scenario_id=scenario, opacity=opacity,
                          lan=True, debug=dbg, mode=station_mode)
    qr_svg = qrgen.make_qr_svg(url, scale=10)
    # 🐞 Debug-QR toggle (RB-003 QA): the same launch with the on-screen console + morph-QA
    # panel + translucency slider, so the operator can hand a tablet the debug build straight
    # from the control room (no desktop PNG) — e.g. Mr. Hayes (P-014) for fidelity/voice QA.
    toggle_href = (f"/portal/face/launch/{_quote(character_id)}"
                   f"?scenario={_quote(scenario, safe='')}&opacity={opacity:.2f}"
                   f"&debug={0 if dbg else 1}")
    toggle_label = "← Back to the normal QR" if dbg else "🐞 Debug QR (console + morph-QA panel)"
    debug_badge = ('<div class="meta" style="color:#ffcf6b">🐞 DEBUG build — on-screen console '
                   '+ morph-QA panel + translucency slider</div>') if dbg else ""
    name = info["name"]
    role = info["role"]
    if info["portrait_source"] == "file":
        portrait = "custom portrait ✓"
    else:
        portrait = (
            f"placeholder — drop a consented photo at "
            f"<code>portal/data/face_portraits/{character_id}.png</code> for a custom face"
        )
    role_line = f'<div class="meta">{role}</div>' if role else ""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VRAI Faces — {name}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif;
          background: #0b0f1a; color: #e9edf5; margin: 0; padding: 32px;
          display: flex; flex-direction: column; align-items: center; }}
  h1 {{ font-size: 20px; font-weight: 500; margin-bottom: 2px; }}
  .qr {{ background: #fff; padding: 16px; border-radius: 12px; }}
  code {{ background: #1c2333; padding: 4px 8px; border-radius: 4px;
          font-size: 13px; word-break: break-all; }}
  .meta {{ margin-top: 14px; font-size: 14px; color: #b5bccd; }}
</style></head><body>
  <h1>{('Assign avatar to a tablet — ' + name) if is_avatar else ('Assign 🔊 AUDIO station to a tablet — ' + name)}</h1>
  {'' if is_avatar else '<div class="meta" style="color:#9fb3d9">Audio-only: flat portrait + voice + push-to-talk — no 3D rig (low-cost tablets OK)</div>'}
  {role_line}
  <div class="meta">Portrait: {portrait}</div>
  {debug_badge}
  <div class="meta">Scan on the tablet to open this avatar full-screen:</div>
  <div class="qr">{qr_svg}</div>
  <div class="meta">scenario: <code>{scenario}</code> &nbsp; opacity: <code>{opacity:.2f}</code></div>
  <div class="meta"><a href="{toggle_href}" style="color:#7fd1ff">{toggle_label}</a></div>
  <div class="meta">URL: <code>{url}</code></div>
  <div class="meta">Schema: VRAISpeechFrame v1 (Memory_management.MD §6.2)</div>
</body></html>"""
    return HTMLResponse(html)
