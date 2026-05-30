"""VRAI Faces ⇄ portal integration (v8, Phase 4.3).

The portal side of the avatar loop. Three responsibilities:

  1. Launchable-character list — GET /api/face/characters
     Which characters can be opened on a tablet right now (Phase 0
     decision 6). Reuses scenarios.list_characters()/list_scenarios().

  2. Bind payload (portrait attach) — GET /api/face/{id}/binding
     The document the avatar page fetches after the QR opens it. This is
     the ONE place a portrait is attached to a character — the MedSim card
     (schemas/character.json) carries none. The payload is the card merged
     with { sourcePhoto, speechWsUrl, ghostColor?, opacityLevel } — exactly
     what medsim_adapter.bindFromCharacter() consumes. No auth: same trust
     level as the no-auth /qr/face deep link that opened it. Presentation
     data only — never PHI.

  3. Speech transport + speak path — WS /ws/face/{scenario}/{id}
     and POST /api/face/{id}/speak
     The avatar connects the WebSocket (medsim_adapter speechWsUrl,
     ADR-0007); the portal pushes VRAISpeechFrame v1 envelopes
     (Memory_management.MD §6.2). Frames carry TEXT + emotion only — the
     tablet synthesizes audio on-device (Kokoro, ADR-0001/0014); no audio
     bytes and no trainee free-text ever cross this wire.

Mirrors ws_room.py: a manager (connect/disconnect/broadcast) + a convenience
emitter (push_speech) + a ws handler + attach(app). Nothing here is a system
of record; scenario/character YAML stays read-only.
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from . import auth, credentials, library, scenarios

# Facilitator-supplied, consented portraits live here, one per character id
# (e.g. patel_attending.png). The portal only ever READS local files — it
# never fetches, scrapes, or gathers facial images. When a character has no
# portrait on disk, a neutral non-photographic placeholder is served so the
# pipeline still runs (mesh_builder falls back to canonical topology).
PORTRAITS_DIR = Path(__file__).resolve().parent / "data" / "face_portraits"
_PORTRAIT_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_MAX_PORTRAIT_BYTES = 8 * 1024 * 1024  # 8 MB safety cap on inlined images

DEFAULT_OPACITY = 0.66  # table mid-stop; matches the QR launcher default

# A neutral, deliberately abstract head-and-shoulders silhouette. Contains no
# real face — its only job is to keep the bind/render path alive when no
# consented portrait has been dropped in. Slate tones match the launcher.
_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
    'viewBox="0 0 512 512" role="img" aria-label="No portrait" '
    'data-vrai-placeholder="1">'
    '<rect width="512" height="512" fill="#0b0f1a"/>'
    '<circle cx="256" cy="196" r="92" fill="#2a3550"/>'
    '<path d="M96 460c0-88 72-150 160-150s160 62 160 150z" fill="#2a3550"/>'
    "</svg>"
)


def _placeholder_portrait() -> str:
    b64 = base64.b64encode(_PLACEHOLDER_SVG.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def resolve_portrait(character_id: str) -> tuple[str, str]:
    """(data_uri, source) for a character's portrait. source ∈ {"file",
    "placeholder"}. Reads a local consented file if present; else the neutral
    placeholder. Never reaches the network."""
    cid = (character_id or "").strip()
    if cid and PORTRAITS_DIR.is_dir():
        for suffix in _PORTRAIT_SUFFIXES:
            p = PORTRAITS_DIR / f"{cid}{suffix}"
            if p.is_file():
                raw = p.read_bytes()
                if len(raw) <= _MAX_PORTRAIT_BYTES:
                    mime = mimetypes.guess_type(p.name)[0] or "image/png"
                    b64 = base64.b64encode(raw).decode("ascii")
                    return f"data:{mime};base64,{b64}", "file"
    return _placeholder_portrait(), "placeholder"


def has_portrait(character_id: str) -> bool:
    """True when a custom consented portrait file exists for this character —
    i.e. an avatar has been assigned/developed for it, as opposed to falling
    back to the generic placeholder silhouette."""
    cid = (character_id or "").strip()
    if not cid or not PORTRAITS_DIR.is_dir():
        return False
    return any((PORTRAITS_DIR / f"{cid}{suf}").is_file() for suf in _PORTRAIT_SUFFIXES)


# ── Skin library ──────────────────────────────────────────────────────
# A "skin" is a labeled portrait the facilitator saves once and assigns to any
# character/persona, instead of re-importing a face each time. Stored as
# data/face_skins/<id>.<ext> (+ <id>.json sidecar). Assigning copies the image
# into face_portraits/<character_id>, which the avatar + scenario badge read.
SKINS_DIR = Path(__file__).resolve().parent / "data" / "face_skins"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _safe_id(value: str) -> str:
    """Reject anything that isn't a plain id token (path-traversal guard)."""
    v = (value or "").strip()
    return v if _ID_RE.match(v) else ""


def list_skins() -> list[dict[str, Any]]:
    """Saved skins, newest first: {id, label, ext, created}."""
    if not SKINS_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for meta in SKINS_DIR.glob("*.json"):
        try:
            d = json.loads(meta.read_text())
        except (OSError, ValueError):
            continue
        out.append({
            "id": d.get("id") or meta.stem,
            "label": d.get("label") or meta.stem,
            "ext": d.get("ext") or "png",
            "created": d.get("created") or 0,
        })
    out.sort(key=lambda s: s["created"], reverse=True)
    return out


def save_skin(label: str, data: bytes, ext: str) -> dict[str, Any]:
    """Persist a skin (image bytes + label). Returns its metadata."""
    SKINS_DIR.mkdir(parents=True, exist_ok=True)
    ext = (ext or "png").lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    if f".{ext}" not in _PORTRAIT_SUFFIXES and ext != "jpg":
        ext = "png"
    skin_id = secrets.token_urlsafe(6)
    (SKINS_DIR / f"{skin_id}.{ext}").write_bytes(data)
    meta: dict[str, Any] = {
        "id": skin_id,
        "label": (label or "").strip()[:80] or "Untitled skin",
        "ext": ext,
        "created": int(time.time()),
    }
    (SKINS_DIR / f"{skin_id}.json").write_text(json.dumps(meta))
    return meta


def skin_image_path(skin_id: str) -> Path | None:
    sid = _safe_id(skin_id)
    if not sid or not SKINS_DIR.is_dir():
        return None
    for suf in _PORTRAIT_SUFFIXES:
        p = SKINS_DIR / f"{sid}{suf}"
        if p.is_file():
            return p
    return None


def delete_skin(skin_id: str) -> bool:
    sid = _safe_id(skin_id)
    if not sid:
        return False
    removed = False
    img = skin_image_path(sid)
    if img:
        img.unlink()
        removed = True
    meta = SKINS_DIR / f"{sid}.json"
    if meta.is_file():
        meta.unlink()
        removed = True
    return removed


def _skin_marker(cid: str) -> Path:
    """Sidecar recording which skin id is assigned to a character (so the picker
    can highlight the current/prior selection — the copied image alone can't)."""
    return PORTRAITS_DIR / f"{cid}.skin"


def assign_skin(skin_id: str, character_id: str) -> bool:
    """Copy a skin's image into face_portraits/<character_id> so it becomes that
    character's assigned avatar (replacing any existing portrait for the id)."""
    src = skin_image_path(skin_id)
    cid = _safe_id(character_id)
    if src is None or not cid:
        return False
    PORTRAITS_DIR.mkdir(parents=True, exist_ok=True)
    for suf in _PORTRAIT_SUFFIXES:           # clear any existing portrait (any ext)
        ex = PORTRAITS_DIR / f"{cid}{suf}"
        if ex.is_file():
            ex.unlink()
    shutil.copyfile(src, PORTRAITS_DIR / f"{cid}{src.suffix}")
    try:
        _skin_marker(cid).write_text(_safe_id(skin_id))
    except OSError:
        pass
    return True


def assigned_skin_id(character_id: str) -> str | None:
    """The skin id currently assigned to a character, if recorded."""
    cid = _safe_id(character_id)
    if not cid:
        return None
    m = _skin_marker(cid)
    if m.is_file():
        try:
            return _safe_id(m.read_text().strip()) or None
        except OSError:
            return None
    return None


def clear_portrait(character_id: str) -> bool:
    """Remove a character's assigned avatar (portrait + marker) → back to none."""
    cid = _safe_id(character_id)
    if not cid:
        return False
    removed = False
    for suf in _PORTRAIT_SUFFIXES:
        p = PORTRAITS_DIR / f"{cid}{suf}"
        if p.is_file():
            p.unlink()
            removed = True
    m = _skin_marker(cid)
    if m.is_file():
        m.unlink()
    return removed


def voice_id_from_profile(vp: dict[str, Any] | None) -> str:
    """Mirror medsim_adapter.voiceIdFromProfile: "<gender>:<hint>" where hint
    is the first voice_hint, else language, else en-US. Default neutral:en-US."""
    if not isinstance(vp, dict):
        return "neutral:en-US"
    gender = str(vp.get("gender") or "neutral").strip().lower()
    if gender not in ("female", "male", "neutral"):
        gender = "neutral"
    hint = ""
    hints = vp.get("voice_hints")
    if isinstance(hints, list) and hints:
        hint = str(hints[0] or "").strip()
    if not hint:
        hint = str(vp.get("language") or "en-US").strip() or "en-US"
    return f"{gender}:{hint}"


def _ghost_color(scenario: dict[str, Any] | None,
                 character: dict[str, Any] | None) -> str | None:
    """Per-scenario ghost tint (Phase 0 decision 4). A character override wins;
    else the scenario; else None (the avatar defaults to clinical white)."""
    for src in (character, scenario):
        if isinstance(src, dict):
            c = src.get("vrai_ghost_color") or src.get("ghost_color")
            if isinstance(c, str) and c.strip():
                return c.strip()
    return None


# ── URL builders ──────────────────────────────────────────────────────

def _portal_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _speech_ws_url(request: Request, scenario_id: str, character_id: str) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    netloc = request.url.netloc  # host[:port]
    return f"{scheme}://{netloc}/ws/face/{scenario_id}/{character_id}"


def _bind_url(request: Request, scenario_id: str, character_id: str,
              opacity: float) -> str:
    return (f"{_portal_origin(request)}/api/face/{character_id}/binding"
            f"?scenario={quote(scenario_id, safe='')}&opacity={opacity:.2f}")


# ── Speech-frame transport ────────────────────────────────────────────

class _FaceManager:
    """Speech-frame subscribers keyed by (scenario_id, character_id). Mirrors
    ws_room._RoomManager. Holds a monotonic seq per key so VRAISpeechFrame.seq
    is strictly increasing even across utterances; the seq is seeded from the
    wall clock so a portal restart never replays a value the avatar has already
    seen (medsim_adapter drops frames whose seq <= lastSeq)."""

    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}
        self._seq: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def key(scenario_id: str, character_id: str) -> str:
        return f"{scenario_id}::{character_id}"

    async def connect(self, key: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._subs.setdefault(key, set()).add(ws)

    async def disconnect(self, key: str, ws: WebSocket) -> None:
        async with self._lock:
            bucket = self._subs.get(key)
            if bucket and ws in bucket:
                bucket.discard(ws)
                if not bucket:
                    self._subs.pop(key, None)

    def subscriber_count(self, scenario_id: str, character_id: str) -> int:
        return len(self._subs.get(self.key(scenario_id, character_id), ()))

    def next_seq(self, key: str) -> int:
        # Lazily seed from ms-since-epoch so restarts move forward, then ++.
        cur = self._seq.get(key)
        if cur is None:
            cur = int(time.time() * 1000)
        cur += 1
        self._seq[key] = cur
        return cur

    async def broadcast(self, key: str, frame: dict[str, Any]) -> int:
        """Send ``frame`` to every subscriber of ``key``. Closed sockets are
        pruned silently. Returns the number of successful sends."""
        async with self._lock:
            bucket = list(self._subs.get(key, ()))
        dead: list[WebSocket] = []
        sent = 0
        for ws in bucket:
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_json(frame)
                    sent += 1
                else:
                    dead.append(ws)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                live = self._subs.get(key)
                if live:
                    for ws in dead:
                        live.discard(ws)
                    if not live:
                        self._subs.pop(key, None)
        return sent


manager = _FaceManager()


def speech_frame(character_id: str, seq: int, *, text: str,
                 emotion: dict[str, Any] | None = None,
                 end_of_utterance: bool = True) -> dict[str, Any]:
    """A VRAISpeechFrame v1 (Memory_management.MD §6.2; shared.ts). Text +
    optional emotion only — no audio bytes (the tablet synthesizes locally,
    ADR-0001/0014)."""
    frame: dict[str, Any] = {
        "v": 1,
        "characterId": character_id,
        "seq": seq,
        "text": text,
        "endOfUtterance": end_of_utterance,
    }
    if (isinstance(emotion, dict)
            and isinstance(emotion.get("label"), str)
            and isinstance(emotion.get("weights"), dict)):
        frame["emotion"] = {
            "label": emotion["label"],
            "weights": {k: float(v) for k, v in emotion["weights"].items()
                        if isinstance(v, (int, float))},
        }
    return frame


async def push_speech(scenario_id: str, character_id: str, *, text: str,
                      emotion: dict[str, Any] | None = None,
                      end_of_utterance: bool = True) -> dict[str, Any]:
    """Build the next frame for (scenario, character) and broadcast it to every
    connected avatar. Returns {seq, delivered}. Call this in-process from the
    MedSim runtime, or via POST /api/face/{id}/speak."""
    key = _FaceManager.key(scenario_id, character_id)
    seq = manager.next_seq(key)
    frame = speech_frame(character_id, seq, text=text, emotion=emotion,
                         end_of_utterance=end_of_utterance)
    delivered = await manager.broadcast(key, frame)
    return {"seq": seq, "delivered": delivered}


# ── Read models ───────────────────────────────────────────────────────

def launchable_characters(request: Request) -> list[dict[str, Any]]:
    """Every character, annotated with the scenarios that reference it and the
    URLs a facilitator/tablet needs. "Launchable" = referenced by >=1 scenario
    (Phase 0 decision 6); orphan characters are listed with launchable=False."""
    scen_for: dict[str, list[str]] = {}
    for s in scenarios.list_scenarios():
        sid = str(s.get("id") or "")
        for cid in s.get("characters") or []:
            scen_for.setdefault(str(cid), []).append(sid)
    out: list[dict[str, Any]] = []
    for c in scenarios.list_characters():
        cid = str(c.get("id") or "")
        scens = scen_for.get(cid, [])
        default_scen = scens[0] if scens else "default"
        out.append({
            "id": cid,
            "name": c.get("name") or cid,
            "role": c.get("role") or "",
            "scenarios": scens,
            "launchable": bool(scens),
            "scenario": default_scen,
            "bind_url": _bind_url(request, default_scen, cid, DEFAULT_OPACITY),
            "speech_ws_url": _speech_ws_url(request, default_scen, cid),
            "qr_url": f"/qr/face/{cid}.svg?scenario={quote(default_scen, safe='')}",
            "launcher_url":
                f"/portal/face/launch/{cid}?scenario={quote(default_scen, safe='')}",
        })
    return out


def resolve_card(character_id: str) -> dict[str, Any] | None:
    """Resolve a renderable character card. Prefers a `characters/*.yaml` card;
    falls back to the 24-persona library (`P-0xx`) so a persona — the roster the
    instructor actually picks from — also yields an avatar. None if neither has it."""
    card = scenarios.get_character(character_id)
    if card is not None:
        return card
    persona = library.get_persona(character_id)
    if persona is not None:
        return library.persona_as_character(persona)
    return None


def launch_info(character_id: str) -> dict[str, Any]:
    """Display info for the facilitator launcher page: resolved name/role and
    whether a real portrait has been dropped in yet (vs the placeholder)."""
    card = resolve_card(character_id)
    _, portrait_source = resolve_portrait(character_id)
    return {
        "id": character_id,
        "name": (card or {}).get("name") or character_id,
        "role": (card or {}).get("role") or "",
        "exists": card is not None,
        "portrait_source": portrait_source,  # 'file' | 'placeholder'
    }


def bind_payload(request: Request, scenario_id: str, character_id: str,
                 opacity: float) -> dict[str, Any] | None:
    """The avatar's bind document: the MedSim card merged with the portrait,
    the speech WebSocket URL, the ghost tint, and opacity — the shape
    medsim_adapter.bindFromCharacter() consumes. None if the character is
    unknown. Presentation data only; never PHI."""
    card = resolve_card(character_id)
    if card is None:
        return None
    scenario = scenarios.get_scenario(scenario_id)
    portrait, portrait_source = resolve_portrait(character_id)
    op = max(0.0, min(1.0, opacity))
    payload: dict[str, Any] = dict(card)  # shallow copy; never mutate the YAML
    payload["characterId"] = card.get("id") or character_id
    payload["sourcePhoto"] = portrait            # adapter extractPhoto() key
    payload["portraitSource"] = portrait_source  # telemetry; adapter ignores
    payload["voiceProfile"] = voice_id_from_profile(card.get("voice_profile"))
    payload["opacityLevel"] = op
    payload["speechWsUrl"] = _speech_ws_url(request, scenario_id, character_id)
    ghost = _ghost_color(scenario, card)
    if ghost is not None:
        payload["ghostColor"] = ghost
    return payload


# ── WebSocket endpoint ────────────────────────────────────────────────

async def handle_face_ws(ws: WebSocket, scenario_id: str,
                         character_id: str) -> None:
    """One-way push channel (server → avatar). The avatar sends nothing; we
    read-and-discard to detect disconnects. Mirrors ws_room.handle_room_ws."""
    key = _FaceManager.key(scenario_id, character_id)
    await manager.connect(key, ws)
    try:
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                break
    finally:
        await manager.disconnect(key, ws)


# ── Wiring ────────────────────────────────────────────────────────────

def attach(app: FastAPI, jinja: Any = None) -> None:
    """Register the VRAI Faces integration routes. Called once from server.py,
    mirroring devices.routes.attach()."""

    @app.get("/api/face/characters")
    async def api_face_characters(  # noqa: ANN202
        request: Request,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        """Facilitator-facing: characters launchable onto a tablet, with their
        QR / bind / speech URLs."""
        return JSONResponse({"characters": launchable_characters(request)})

    @app.get("/api/face/{character_id}/binding")
    async def api_face_binding(  # noqa: ANN202
        request: Request,
        character_id: str,
        scenario: str = "default",
        opacity: float = DEFAULT_OPACITY,
    ):
        """Avatar-facing (no auth — same trust as the /qr/face deep link that
        opened the tablet). The bind document, with the portrait attached."""
        payload = bind_payload(request, scenario, character_id, opacity)
        if payload is None:
            return JSONResponse(
                {"ok": False, "error": f"character {character_id} not found"},
                status_code=404,
            )
        return JSONResponse(payload)

    @app.post("/api/face/{character_id}/speak")
    async def api_face_speak(  # noqa: ANN202
        request: Request,
        character_id: str,
        _: Annotated[credentials.Vault, Depends(auth.require_vault)],
    ):
        """Push one spoken line (text + optional emotion) to every avatar bound
        to (scenario, character). The tablet synthesizes the audio locally."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            body = {}
        text = str(body.get("text") or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text required"},
                                status_code=400)
        scenario = str(body.get("scenario") or "default")
        emotion = body.get("emotion")
        result = await push_speech(
            scenario, character_id, text=text,
            emotion=emotion if isinstance(emotion, dict) else None,
        )
        return JSONResponse({"ok": True, **result})

    @app.post("/api/face/skins")
    async def api_face_skins(  # noqa: ANN202
        label: Annotated[str, Form()] = "",
        image: UploadFile = File(...),
    ):
        """Save a skin pushed from the VRAI Faces app's 'Save skin' button.
        No auth (same trust as the binding GET); CORS allows the app origin.
        The portal's own /portal/skins library reads the same store."""
        data = await image.read()
        if not data:
            return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
        if len(data) > _MAX_PORTRAIT_BYTES:
            return JSONResponse({"ok": False, "error": "too large"}, status_code=413)
        fn = image.filename or ""
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "png"
        skin = save_skin(label, data, ext)
        return JSONResponse({"ok": True, "id": skin["id"], "label": skin["label"]})

    @app.websocket("/ws/face/{scenario_id}/{character_id}")
    async def ws_face(ws: WebSocket, scenario_id: str,  # noqa: ANN202
                      character_id: str):
        await handle_face_ws(ws, scenario_id, character_id)
