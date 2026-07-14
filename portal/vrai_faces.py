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
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import struct
import time
import zlib
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

# ── Device token (ADR-0027 hardening — OPT-IN via MEDSIM_FACE_TOKEN) ──────────
# A per-(scenario,character) capability minted into the QR/launch URL and required
# on the AI-spend route POST /api/face/<id>/listen, so a stray LAN client that
# never scanned the QR can't drive an avatar or spend Anthropic budget. Stateless
# HMAC over "<scenario>|<character>" with a per-deployment secret. OFF by default
# (no behavior change; pilots unaffected) — set MEDSIM_FACE_TOKEN=1 to enforce.
_TOKEN_SECRET_FILE = Path(__file__).resolve().parent / "data" / ".face_token_secret"
_token_secret_cache: bytes | None = None


def token_enabled() -> bool:
    return bool((os.environ.get("MEDSIM_FACE_TOKEN") or "").strip())


def _token_secret() -> bytes:
    global _token_secret_cache
    if _token_secret_cache is None:
        try:
            if _TOKEN_SECRET_FILE.is_file():
                _token_secret_cache = _TOKEN_SECRET_FILE.read_bytes()
            else:
                _TOKEN_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
                sec = secrets.token_bytes(32)
                _TOKEN_SECRET_FILE.write_bytes(sec)
                _token_secret_cache = sec
        except OSError:
            _token_secret_cache = secrets.token_bytes(32)  # ephemeral (this run only)
    return _token_secret_cache


def face_token(scenario_id: str, character_id: str) -> str:
    """A short capability token for (scenario, character). Stable per deployment."""
    msg = f"{(scenario_id or '').strip()}|{(character_id or '').strip()}".encode("utf-8")
    return hmac.new(_token_secret(), msg, hashlib.sha256).hexdigest()[:24]

# A neutral solid-slate placeholder for characters with no assigned avatar. It
# MUST be a raster (PNG): the VRAI Faces app decodes portraits with the browser's
# createImageBitmap(), which cannot decode SVG in Chromium — an SVG placeholder
# made face_ingest throw and blanked the app. mesh_builder falls back to the
# canonical face topology on a featureless image, so this renders a plain head.

def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A minimal valid solid-color RGB PNG (stdlib only — no PIL)."""
    row = b"\x00" + bytes(rgb) * width            # filter byte 0 + W RGB pixels
    raw = row * height

    def _chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


_PLACEHOLDER_PNG_B64 = base64.b64encode(_solid_png(256, 256, (42, 53, 80))).decode("ascii")


def _placeholder_portrait() -> str:
    return f"data:image/png;base64,{_PLACEHOLDER_PNG_B64}"


def _file_data_uri(p: Path) -> str | None:
    """Read a local image file → data: URI, or None if missing / too large."""
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    if len(raw) > _MAX_PORTRAIT_BYTES:
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def resolve_portrait(character_id: str) -> tuple[str, str]:
    """(data_uri, source) for a character's portrait. source ∈ {"file",
    "placeholder"}. Resolution order: a dropped consented file, then the skin
    assigned via the picker, then the neutral placeholder. Never hits the
    network.

    NOTE: assigning a skin COPIES it into face_portraits/<id> (the first check),
    so the marker fallback below is belt-and-suspenders — it still resolves an
    assignment whose copied file went missing. A *saved* skin that was never
    assigned to this character yields the placeholder (the blank head-proxy)."""
    cid = (character_id or "").strip()
    if cid and PORTRAITS_DIR.is_dir():
        for suffix in _PORTRAIT_SUFFIXES:
            p = PORTRAITS_DIR / f"{cid}{suffix}"
            if p.is_file():
                uri = _file_data_uri(p)
                if uri:
                    return uri, "file"
    # Honor an assigned-skin marker even if the copied portrait file is absent.
    sid = assigned_skin_id(cid)
    if sid:
        sp = skin_image_path(sid)
        if sp is not None:
            uri = _file_data_uri(sp)
            if uri:
                return uri, "file"
    return _placeholder_portrait(), "placeholder"


def has_portrait(character_id: str) -> bool:
    """True when a custom consented portrait file exists for this character —
    i.e. an avatar has been assigned/developed for it, as opposed to falling
    back to the generic placeholder silhouette."""
    cid = (character_id or "").strip()
    if not cid or not PORTRAITS_DIR.is_dir():
        return False
    return any((PORTRAITS_DIR / f"{cid}{suf}").is_file() for suf in _PORTRAIT_SUFFIXES)


def is_portrait_ai(character_id: str) -> bool:
    """True when this character's portrait is AI-generated (synthetic), so the
    UI can show the "AI-generated" disclosure badge (EU AI Act Art. 50 posture).

    Two signals, either suffices:
    1. `<id>.ai.json` sidecar in face_portraits/ — FACE ENGINE writes this
       declaration next to every portrait it exports (same sidecar convention
       as the `.skin` marker).
    2. The image's embedded C2PA manifest declares the IPTC
       `trainedAlgorithmicMedia` source type (the standard machine-readable
       "AI-generated" marking). NOTE: mere presence of C2PA is NOT the test —
       real cameras embed C2PA capture manifests too."""
    cid = (character_id or "").strip()
    if not cid or not PORTRAITS_DIR.is_dir():
        return False
    if (PORTRAITS_DIR / f"{cid}.ai.json").is_file():
        return True
    for suffix in _PORTRAIT_SUFFIXES:
        p = PORTRAITS_DIR / f"{cid}{suffix}"
        if p.is_file():
            try:
                head = p.read_bytes()[: 4 * 1024 * 1024]
            except OSError:
                return False
            return b"trainedAlgorithmicMedia" in head
    return False


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
                 end_of_utterance: bool = True,
                 audio_b64: str | None = None,
                 audio_format: str | None = None) -> dict[str, Any]:
    """A VRAISpeechFrame v1 (Memory_management.MD §6.2; shared.ts). Text +
    optional emotion. Optionally carries pre-synthesized audio (base64) when the
    portal voices the line server-side (ADR-0031, ElevenLabs) — for tablets that
    can't run the on-device ONNX TTS; otherwise the tablet synthesizes locally
    (ADR-0001/0014). The audio is the *character's* reply, never trainee
    free-text, so it moves no PHI off-portal."""
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
    if audio_b64:
        # JSON (ws.send_json) can't carry raw bytes → base64; medsim_adapter's
        # parseFrame hydrates this back into an ArrayBuffer (audioB64 → audio).
        frame["audioB64"] = audio_b64
        frame["audioFormat"] = audio_format or "mp3"
    return frame


async def push_speech(scenario_id: str, character_id: str, *, text: str,
                      emotion: dict[str, Any] | None = None,
                      end_of_utterance: bool = True,
                      audio_b64: str | None = None,
                      audio_format: str | None = None) -> dict[str, Any]:
    """Build the next frame for (scenario, character) and broadcast it to every
    connected avatar. Returns {seq, delivered, voiced}. Pass audio_b64 to voice
    the line server-side (the avatar plays it instead of synthesizing locally).
    Call this in-process from the MedSim runtime, or via POST /api/face/{id}/speak."""
    key = _FaceManager.key(scenario_id, character_id)
    seq = manager.next_seq(key)
    frame = speech_frame(character_id, seq, text=text, emotion=emotion,
                         end_of_utterance=end_of_utterance,
                         audio_b64=audio_b64, audio_format=audio_format)
    delivered = await manager.broadcast(key, frame)
    return {"seq": seq, "delivered": delivered, "voiced": bool(audio_b64)}


def _first_sentence_cut(buf: str, min_first: int = 25, max_scan: int = 280) -> int | None:
    """Index just AFTER the first sentence boundary (`.`/`!`/`?` followed by whitespace), at/after
    `min_first` chars and NEVER inside a `*stage direction*` (persona replies open with them).
    None when no usable boundary (yet) — safe to call incrementally on a growing buffer (OPT-008
    Cut 2 streams deltas through it until a boundary appears)."""
    in_star = False
    for i, ch in enumerate(buf[:max_scan]):
        if ch == "*":
            in_star = not in_star
            continue
        if in_star:
            continue
        if ch in ".!?" and i + 1 < len(buf) and buf[i + 1] in " \n\t" and i + 1 >= min_first:
            return i + 1
    return None


def _split_reply(reply: str, min_first: int = 25, max_scan: int = 280) -> tuple[str, str]:
    """OPT-008 Cut 1 (pipelined TTS): split a COMPLETE reply into (first sentence(s), remainder)
    so the first chunk can be voiced + pushed immediately while the tail synthesizes. Returns
    (reply, "") when the reply is short, unbalanced, or has no usable boundary — the caller then
    sends today's single frame, so this can only ever help."""
    text = reply.strip()
    if len(text) <= min_first * 2:
        return text, ""
    cut = _first_sentence_cut(text, min_first, max_scan)
    if cut is None:
        return text, ""
    first, rest = text[:cut].strip(), text[cut:].strip()
    if first and rest:
        return first, rest
    return text, ""


# Strong refs to fire-and-forget tail-synth tasks (asyncio only weak-refs running tasks).
_speech_tail_tasks: set[Any] = set()


async def _voice_and_push_line(
    sess: Any, cid: str, scenario_id: str, line: str,
    emotion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Voice a COMPLETE line server-side and push it to the avatar, first-sentence
    pipelined (the OPT-008 Cut-1 shape, shared by FR-003 instructor lines): synth + push
    the first sentence immediately, finish the tail in a background task (text-only frame
    on synth failure so a line is never half-silent). Falls back to a single frame for
    short lines or when no server voice is available (device speaks it locally)."""
    first, rest = _split_reply(line)
    if rest:
        b64, fmt = await _synthesize_voice(sess, cid,first)
        if b64:
            spoken = await push_speech(scenario_id, cid, text=first, emotion=emotion,
                                       audio_b64=b64, audio_format=fmt,
                                       end_of_utterance=False)

            async def _tail() -> None:
                tail_b64: str | None = None
                tail_fmt: str | None = None
                try:
                    tail_b64, tail_fmt = await _synthesize_voice(sess, cid,rest)
                except Exception:  # noqa: BLE001 — text-only keeps the line audible
                    tail_b64, tail_fmt = None, None
                try:
                    await push_speech(scenario_id, cid, text=rest, emotion=emotion,
                                      audio_b64=tail_b64, audio_format=tail_fmt)
                except Exception:  # noqa: BLE001 — never crash from a bg task
                    import logging
                    logging.getLogger(__name__).warning(
                        "voiced-line tail push failed for %s", cid, exc_info=True)

            import asyncio as _aio
            t = _aio.create_task(_tail())
            _speech_tail_tasks.add(t)
            t.add_done_callback(_speech_tail_tasks.discard)
            return {"streamed": True, **spoken}
    b64, fmt = await _synthesize_voice(sess, cid,line)
    spoken = await push_speech(scenario_id, cid, text=line, emotion=emotion,
                               audio_b64=b64, audio_format=fmt)
    return {"streamed": False, **spoken}


async def _stream_reply_turn(
    sess: Any, sim_id: str, cid: str, scenario_id: str, user_text: str,
    persona_name: str,
) -> dict[str, Any] | None:
    """OPT-008 Cut 2: run the character turn STREAMED — voice + push the FIRST sentence the
    moment the LLM produces it (while the rest is still generating), ACK immediately, and
    finish everything else (rest of stream → tail synth+push → operator log → session cleanup)
    in a background task. Returns the ack dict, or None if the stream failed BEFORE anything
    was pushed (the caller then falls back to the blocking turn — never a double reply)."""
    import asyncio
    from . import runtime

    try:
        gen = runtime.take_turn_stream(sim_id, cid, user_text)
    except Exception:  # noqa: BLE001 — validation failure → blocking fallback
        return None

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _pump() -> None:
        """Drain the sync Anthropic stream on a worker thread → the async queue."""
        err: Exception | None = None
        try:
            for delta in gen:
                loop.call_soon_threadsafe(q.put_nowait, ("delta", delta))
        except Exception as exc:  # noqa: BLE001 — surfaced to the async side
            err = exc
        loop.call_soon_threadsafe(q.put_nowait, ("end", err))

    loop.run_in_executor(None, _pump)

    buf = ""
    cut_at: int | None = None
    first: str | None = None
    spoken: dict[str, Any] = {}
    deadline = loop.time() + 30.0
    stream_done = False
    stream_err: Exception | None = None

    # Phase 1 (the latency-critical part): consume deltas just until the first sentence
    # boundary, then synth + push it. Everything after is off the perceived-latency path.
    while not stream_done and first is None:
        timeout = deadline - loop.time()
        if timeout <= 0:
            return None        # nothing pushed yet → safe blocking fallback
        try:
            kind, val = await asyncio.wait_for(q.get(), timeout)
        except asyncio.TimeoutError:
            return None
        if kind == "delta":
            buf += val
            cut_at = _first_sentence_cut(buf)
            if cut_at is not None:
                first = buf[:cut_at].strip()
                b64, fmt = await _synthesize_voice(sess, cid,first)
                spoken = await push_speech(scenario_id, cid, text=first,
                                           audio_b64=b64, audio_format=fmt,
                                           end_of_utterance=False)
        else:
            stream_done = True
            stream_err = val

    if first is None:
        # Stream ended with no usable boundary. Errors → fallback; a clean short reply →
        # behave exactly like the single-frame path (synth the whole thing now, ack after).
        if stream_err is not None or not buf.strip():
            return None
        reply = buf.strip()
        b64, fmt = await _synthesize_voice(sess, cid,reply)
        spoken = await push_speech(scenario_id, cid, text=reply,
                                   audio_b64=b64, audio_format=fmt)
        _finish_streamed_turn(sess, sim_id, cid, persona_name, user_text, reply, None)
        return {"ok": True, "heard": user_text, "reply": reply, "mode": "ai",
                "streamed": "llm", **spoken}

    # First sentence is already speaking on the device. Finish the rest in the background.
    tail_from = cut_at or 0

    async def _finish() -> None:
        nonlocal buf
        try:
            done = stream_done
            while not done:
                kind, val = await asyncio.wait_for(q.get(), 60.0)  # generous: off the hot path
                if kind == "delta":
                    buf += val
                else:
                    done = True
        except Exception:  # noqa: BLE001 — speak whatever arrived before the stall
            pass
        rest = buf[tail_from:].strip()
        if rest:
            tail_b64: str | None = None
            tail_fmt: str | None = None
            try:
                tail_b64, tail_fmt = await _synthesize_voice(sess, cid,rest)
            except Exception:  # noqa: BLE001 — text-only frame keeps the turn audible
                tail_b64, tail_fmt = None, None
            try:
                await push_speech(scenario_id, cid, text=rest,
                                  audio_b64=tail_b64, audio_format=tail_fmt)
            except Exception:  # noqa: BLE001 — never crash the loop from a bg task
                import logging
                logging.getLogger(__name__).warning(
                    "OPT-008 streamed tail push failed for %s", cid, exc_info=True)
        _finish_streamed_turn(sess, sim_id, cid, persona_name, user_text, buf.strip(), None)

    t = asyncio.get_running_loop().create_task(_finish())
    _speech_tail_tasks.add(t)
    t.add_done_callback(_speech_tail_tasks.discard)
    return {"ok": True, "heard": user_text, "reply": first, "mode": "ai",
            "streamed": "llm", **spoken}


def _finish_streamed_turn(
    sess: Any, sim_id: str, cid: str, persona_name: str,
    user_text: str, reply: str, _unused: Any,
) -> None:
    """Operator-transcript log + throwaway-session cleanup for a streamed turn (the blocking
    path does both inline; streamed turns do them once the FULL reply text is known)."""
    from . import runtime
    if sess is not None and reply:
        try:
            sess.log_turn(
                source=f"device:{cid}",
                source_label=f"{persona_name} · device voice",
                persona_id=cid,
                persona_name=persona_name,
                student_text=user_text,
                character_text=reply,
            )
        except Exception:  # noqa: BLE001 — a logging hiccup must never fail the turn
            pass
        # FR-008 S3: stamp 'delivered' if a staged verbal error was spoken
        # (role self-resolves from the character card; never raises).
        from . import med_errors as _me
        _me.note_character_reply(sess.id, cid, reply)
    runtime.end_session(sim_id)


def _wav_pcm_data(buf: bytes) -> bytes | None:
    """Raw PCM body from a little-endian WAV (RIFF) buffer — the bytes inside the
    'data' chunk. Parses chunks because CoreAudio/afconvert inserts an alignment
    'FLLR' chunk before 'data', so a fixed 44-byte header skip is wrong. None if
    the buffer is not a parseable WAVE."""
    if len(buf) < 12 or buf[0:4] != b"RIFF" or buf[8:12] != b"WAVE":
        return None
    i = 12
    while i + 8 <= len(buf):
        cid = buf[i:i + 4]
        size = int.from_bytes(buf[i + 4:i + 8], "little")
        if cid == b"data":
            return bytes(buf[i + 8:i + 8 + size])
        i += 8 + size + (size & 1)  # RIFF chunks are word-aligned
    return None


async def _local_dev_tts(text: str) -> tuple[str | None, str | None]:
    """TEST-ONLY placeholder TTS (ADR-0037, "validate plumbing first"): synthesize the
    reply with the portal's OS voice (macOS `say`) → raw PCM16 @ 24 kHz mono → base64,
    tagged 'pcm16-24k' (the client's no-decode path). Lets the server-audio → AudioContext
    → envelope-lip-sync path be validated end-to-end on devices that cannot synthesize
    locally (the iPad), WITHOUT ElevenLabs or a session. macOS-only; returns (None, None)
    elsewhere. NOT a production voice — see docs/BROWSER-DEPLOYMENT-STANDARD.md §6 (open
    decision). Gated by VRAI_DEV_TTS so it never fires unless explicitly enabled."""
    import asyncio
    import base64
    import shutil

    say = shutil.which("say")
    afconvert = shutil.which("afconvert")
    if not (say and afconvert):
        return None, None

    def _render() -> bytes | None:
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            aiff = os.path.join(d, "v.aiff")
            wav = os.path.join(d, "v.wav")
            try:
                subprocess.run([say, "-o", aiff, text],
                               check=True, timeout=20, capture_output=True)
                subprocess.run([afconvert, "-f", "WAVE", "-d", "LEI16@24000", aiff, wav],
                               check=True, timeout=20, capture_output=True)
                with open(wav, "rb") as fh:
                    return _wav_pcm_data(fh.read())
            except Exception:  # noqa: BLE001 — a placeholder must never fail the turn
                return None

    pcm = await asyncio.to_thread(_render)
    if not pcm:
        return None, None
    return base64.b64encode(pcm).decode("ascii"), "pcm16-24k"


_standalone_voice_cache: dict[str, str] = {}


async def _standalone_voice_id(character_id: str, api_key: str) -> str:
    """Pick a character-appropriate ElevenLabs voice when no operator has assigned one
    (standalone / device-launched, no control session). Ranked by the persona's traits;
    cached per character. `candidates_for` does a BLOCKING HTTP fetch, so run it off the
    event loop — never block the portal for voice selection."""
    if character_id in _standalone_voice_cache:
        return _standalone_voice_cache[character_id]
    import asyncio
    from . import voices  # lazy
    vid = ""
    try:
        res = await asyncio.to_thread(voices.candidates_for, character_id, api_key)
        cands = res.get("candidates", [])
        if cands:
            vid = str(cands[0].get("voice_id") or "").strip()
    except Exception:  # noqa: BLE001 — never fail the turn over voice selection
        vid = ""
    _standalone_voice_cache[character_id] = vid
    return vid


async def _synthesize_voice(
    sess: Any, character_id: str, text: str,
) -> tuple[str | None, str | None]:
    """Best-effort server-side TTS of an avatar line, returned as (base64, format).
    Order: (1) **ElevenLabs** (ADR-0031/0037 — the chosen production voice) → (base64-mp3,
    "mp3"): the voice is the operator's control-room assignment when a session set one, else
    a character-appropriate candidate (standalone/device-launched); the key is the session's
    captured key, else the process env / `~/.medsim/elevenlabs.key`. (2) a TEST-ONLY OS-voice
    placeholder (ADR-0037), opt-in via VRAI_DEV_TTS, for when ElevenLabs is unavailable →
    (base64-pcm, "pcm16-24k"). Returns (None, None) when neither applies — the caller then
    sends a text-only frame and the device speaks with its built-in voice.

    PHI (ADR-0014): the *reply* is the character's AI-generated words — never trainee
    free-text — so voicing it server-side moves no trainee PHI off-portal; only audio
    crosses the device WS. ElevenLabs is cloud, so the (non-PHI) reply text does leave the
    portal — acceptable per ADR-0031; the trainee's own speech never does (on-device STT)."""
    if not text:
        return None, None

    from . import voices  # lazy: avoid an import-time cycle (mirrors /listen)

    # FR-020: never SPEAK *stage directions* — they stay in the frame text for the
    # display + emotion/animation side. A direction-only line returns (None, None);
    # the client's speak fallback applies the same strip, so it stays unvoiced there too.
    text = voices.strip_stage_directions(text)
    if not text:
        return None, None

    # (1) Managed TTS. The default (ElevenLabs) runs whenever a key exists (session OR env/keyfile),
    #     not just when an operator assigned a voice — behavior unchanged. An alternate provider
    #     (TTS_PROVIDER=azure, gate 1b) runs whenever ITS org-wide env config is present; it maps
    #     the assigned ElevenLabs voice id through the casting map (default voice for anything
    #     unmapped), so the ElevenLabs-catalog standalone-voice lookup is skipped for it.
    from .providers.tts import make_tts
    tts = make_tts()
    api_key = (sess.elevenlabs_api_key
               if sess is not None and getattr(sess, "elevenlabs_api_key", "")
               else voices.get_api_key(None))
    usable = bool(api_key) if tts.name == "elevenlabs" else tts.available()
    if usable:
        voice_id = ""
        if sess is not None:
            assigns = getattr(sess, "voice_assignments", None) or {}
            voice_id = str(assigns.get(character_id, "")).strip()
        if not voice_id and tts.name == "elevenlabs":
            voice_id = await _standalone_voice_id(character_id, api_key)
        if voice_id or tts.name != "elevenlabs":
            try:
                buf = bytearray()
                async for chunk in tts.synthesize_stream(text, voice_id, api_key):
                    buf.extend(chunk)
                if buf:
                    import base64
                    return base64.b64encode(bytes(buf)).decode("ascii"), "mp3"
            except Exception as exc:  # noqa: BLE001 — TTS must never fail the turn
                import logging
                logging.getLogger(__name__).warning(
                    "avatar TTS synth failed (%s); trying dev fallback / device voice", exc)

    # (2) TEST-ONLY OS-voice placeholder (ADR-0037), if ElevenLabs is unavailable + opted in.
    if os.environ.get("VRAI_DEV_TTS", "").strip().lower() in ("say", "1", "true", "on"):
        return await _local_dev_tts(text)

    return None, None  # no voice → text-only frame (device built-in TTS)


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
    payload["portraitIsAi"] = is_portrait_ai(character_id)  # AI-disclosure (Art. 50); additive
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
        """FR-003 — instructor speaks through the character. Push one line to every
        avatar bound to (scenario, character), voiced server-side (ElevenLabs, same
        path as AI replies, first-sentence pipelined; device speaks locally when no
        voice is available).

        Modes (body.mode):
          "verbatim" (default) — speak the instructor's exact words, colored by the
              character's voice + current affect (the device's auto-emote applies).
          "in_character" — the AI rephrases the instructor's INTENT through the
              persona (voice, knowledge boundary, altered_state) via the same system
              prompt as a normal turn. Requires a running scenario (its API key).

        The line is character speech (non-PHI → cloud voice OK, ADR-0037) and is
        logged to the operator transcript like any character turn."""
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
        emo = emotion if isinstance(emotion, dict) else None
        mode = str(body.get("mode") or "verbatim").strip().lower()

        from . import control_session, runtime
        sess = control_session.get_active()
        card = resolve_card(character_id)
        cid = str((card or {}).get("id") or character_id)
        persona_name = str((card or {}).get("name") or cid)

        line = text
        if mode in ("in_character", "incharacter", "ai"):
            mode = "in_character"
            if sess is None or not getattr(sess, "api_key", "") or card is None:
                return JSONResponse(
                    {"ok": False,
                     "error": "in-character mode needs a running scenario"},
                    status_code=409)
            scenario_doc = {
                "id": sess.id,
                "name": getattr(sess, "scenario_name", "") or scenario,
                "patient": ({"history": sess.scenario_text}
                            if getattr(sess, "scenario_text", "") else {}),
            }
            # FR-001/002: same med-board injection as /listen (doctor/pharmacist only).
            # FR-008 S3: staged verbal-error context rides the same channel.
            from . import handoff, local_context, med_errors, med_orders
            _med_ctx = med_orders.prompt_block_for(sess.id, card)
            _err_ctx = med_errors.prompt_block_for(sess.id, card)
            _ho_ctx = handoff.prompt_block_for(sess.id, card)  # FR-009 H2 — counterpart only
            _lc_ctx = local_context.overlay_block()            # FR-013 P4 — local overlay
            _ctx = "\n\n".join(x for x in (_med_ctx, _err_ctx, _ho_ctx, _lc_ctx) if x)
            ic_card = {**card, "_extra_context": _ctx} if _ctx else card
            sim = runtime.create_session_from_data(
                scenario=scenario_doc, characters={cid: ic_card}, api_key=sess.api_key)
            import asyncio
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(runtime.take_instructor_line, sim.id, cid, text),
                    timeout=25.0)
            except asyncio.TimeoutError:
                result = {"ok": False, "error": "character timed out"}
            runtime.end_session(sim.id)
            if not result.get("ok"):
                return JSONResponse(
                    {"ok": False, "error": str(result.get("error"))}, status_code=502)
            line = str(result.get("reply") or "").strip() or text
        else:
            mode = "verbatim"

        # Surface the instructor line in the operator transcript like any turn.
        if sess is not None:
            try:
                sess.log_turn(
                    source=f"instructor:{cid}",
                    source_label=f"{persona_name} · instructor line",
                    persona_id=cid,
                    persona_name=persona_name,
                    student_text=f"[instructor → {persona_name}, {mode}] {text}",
                    character_text=line,
                )
            except Exception:  # noqa: BLE001 — logging must never fail the line
                pass

        spoken = await _voice_and_push_line(sess, cid, scenario, line, emotion=emo)
        return JSONResponse({"ok": True, "mode": mode, "reply": line, **spoken})

    @app.post("/api/face/{character_id}/listen")
    async def api_face_listen(  # noqa: ANN202
        request: Request,
        character_id: str,
    ):
        """Device-facing trainee input (no auth — same trust as the binding/speak
        deep link that opened the tablet). The trainee's transcribed utterance →
        the character AI turn → push_speech, so the avatar answers in its voice.

        DEMO STOPGAP (ADR-0025). The tablet transcribes with the browser's cloud
        Web Speech API, which is NOT PHI-safe — so this path is OFF by default,
        gated behind an explicit 'cloud voice — not for PHI' toggle in the app,
        and is for non-PHI live testing only. The PHI-safe on-device replacement
        is gated on RB-002 (ADR-0024). The AI key is borrowed from the active
        control session; with no running scenario the avatar simply echoes what
        it heard, so the end-to-end mic→STT→portal→avatar loop is still testable.
        """
        # Local imports: keep the cross-module deps lazy (no import-time cycle),
        # mirroring how runtime/operator turn pull the Anthropic client lazily.
        from . import control_session, runtime

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
        scenario_id = str(body.get("scenario") or "default")

        # Device-token capability check (ADR-0027) — only when enforcement is on.
        # The token is minted into the QR/launch URL for (scenario, character), so a
        # LAN client that never scanned the QR can't drive the avatar / spend AI.
        if token_enabled() and not hmac.compare_digest(
                str(body.get("token") or ""), face_token(scenario_id, character_id)):
            return JSONResponse({"ok": False, "error": "invalid device token"},
                                status_code=403)

        card = resolve_card(character_id)
        if card is None:
            return JSONResponse(
                {"ok": False, "error": f"character {character_id} not found"},
                status_code=404,
            )
        cid = str(card.get("id") or character_id)

        # Borrow the running scenario's Anthropic key for a real character reply.
        # No active session (device opened standalone) → echo, so the avatar
        # still speaks and the voice→avatar pipeline can be exercised live.
        try:
            sess = control_session.get_active()
        except Exception:  # noqa: BLE001 — multi-encounter room: no single active session
            sess = None
        persona_name = str(card.get("name") or cid)
        reply = ""
        mode = "echo"
        vsess = sess   # the encounter to borrow voice + transcript from (room: a bed)

        # FR-007 v2 — in a multi-patient room there is no single active session, so a
        # character on a tablet would otherwise ECHO. Resolve it room-aware: a SHARED
        # persona answers as ONE instance spanning every bed; any other character answers
        # for its specific bed (the QR's scenario id, else its roster). The Anthropic key
        # comes from the process cache (room start populates it) — room encounters do NOT
        # carry a stamped api_key, which is exactly why the old `e.api_key` path echoed.
        if sess is None:
            try:
                from . import control_room as _cr
                _room = _cr.get_active_room()
            except Exception:  # noqa: BLE001
                _room = None
            if _room is not None:
                _encs = list(_room.encounters.values())
                from .server import _resolve_anthropic_key as _rkey
                _key = _rkey(_encs[0] if _encs else None)
                _scn = None
                if cid in (getattr(_room, "shared_personas", []) or []):
                    # shared character: one instance, aware of every bed in the room
                    vsess = next((e for e in _encs
                                  if cid in (getattr(e, "voice_assignments", {}) or {})),
                                 (_encs[0] if _encs else None))
                    _rps = [{"label": e.encounter_label or e.scenario_name or "patient",
                             "history": e.scenario_text or ""} for e in _encs]
                    _scn = {"id": getattr(vsess, "id", _room.room_id),
                            "name": _room.label or "Shared care room", "room_patients": _rps}
                else:
                    # a per-bed character: bind to its bed (QR scenario id, else roster)
                    _bed = next((e for e in _encs if e.id == scenario_id), None) \
                        or next((e for e in _encs
                                 if cid in (getattr(e, "selected_personas", []) or [])), None)
                    if _bed is not None:
                        vsess = _bed
                        _scn = {"id": _bed.id,
                                "name": getattr(_bed, "scenario_name", "") or scenario_id,
                                "patient": ({"history": _bed.scenario_text}
                                            if getattr(_bed, "scenario_text", "") else {})}
                # Last resort in a LIVE room: answer room-aware (all beds) rather than
                # echo — covers a character that's neither flagged shared nor matched to
                # a bed roster (e.g. shared_personas didn't survive a resume).
                if _scn is None and _encs:
                    vsess = _encs[0]
                    _rps = [{"label": e.encounter_label or e.scenario_name or "patient",
                             "history": e.scenario_text or ""} for e in _encs]
                    _scn = {"id": _encs[0].id, "name": _room.label or "Care room",
                            "room_patients": _rps}
                if _scn is not None and _key:
                    # FR-009 / FR-001-002 — inject the handoff + med-board + staged-error
                    # prompt blocks for THIS bed (keyed by vsess.id) so a shared/per-bed
                    # character on a tablet actually RUNS the handoff and is grounded in
                    # the med board — parity with the single-session branch below. Each
                    # block is a no-op for a non-counterpart / non-doctor-pharmacist.
                    from . import (handoff as _ho2, local_context as _lc2,
                                   med_errors as _me2, med_orders as _mo2)
                    _hsid = getattr(vsess, "id", None)
                    # FR-013 P4 — local-practice overlay (program-wide, no session
                    # key) applies even when this branch has no bound bed id.
                    _rparts = [_lc2.overlay_block()]
                    if _hsid:
                        _rparts += [_mo2.prompt_block_for(_hsid, card),
                                    _me2.prompt_block_for(_hsid, card),
                                    _ho2.prompt_block_for(_hsid, card)]
                    _rctx = "\n\n".join(x for x in _rparts if x)
                    _rcard = {**card, "_extra_context": _rctx} if _rctx else card
                    _sim = runtime.create_session_from_data(
                        scenario=_scn, characters={cid: _rcard}, api_key=_key)
                    import asyncio as _aio0
                    try:
                        _res = await _aio0.wait_for(
                            _aio0.to_thread(runtime.take_turn, _sim.id, cid, text), timeout=25.0)
                    except _aio0.TimeoutError:
                        _res = {"ok": False, "error": "character timed out"}
                    runtime.end_session(_sim.id)
                    if _res.get("ok"):
                        reply = str(_res.get("reply") or "").strip(); mode = "ai"
                    else:
                        reply = f"(the character could not respond: {_res.get('error')})"
                        mode = "error"

        if not reply and sess is not None:
            # cache-first key: a room/resumed encounter carries NO stamped api_key, but
            # the process cache (kept fresh by the readiness poll) does. Stamp it so the
            # branch below + _stream_reply_turn + create_session all use a live key
            # instead of echoing.
            from .server import _resolve_anthropic_key as _rkey2
            sess.api_key = _rkey2(sess) or getattr(sess, "api_key", "")
        if not reply and sess is not None and getattr(sess, "api_key", ""):
            scenario = {
                "id": sess.id,
                "name": getattr(sess, "scenario_name", "") or scenario_id,
                "patient": ({"history": sess.scenario_text}
                            if getattr(sess, "scenario_text", "") else {}),
            }
            # FR-001/002: doctor/pharmacist personas get the session's medication
            # board injected into their system prompt (authored data; code-selected
            # recommendation — the model never invents drugs/doses). No-op otherwise.
            from . import handoff, local_context, med_errors, med_orders
            _med_ctx = med_orders.prompt_block_for(sess.id, card)
            _err_ctx = med_errors.prompt_block_for(sess.id, card)
            _ho_ctx = handoff.prompt_block_for(sess.id, card)  # FR-009 H2 — counterpart only
            _lc_ctx = local_context.overlay_block()            # FR-013 P4 — local overlay
            _ctx = "\n\n".join(x for x in (_med_ctx, _err_ctx, _ho_ctx, _lc_ctx) if x)
            turn_card = {**card, "_extra_context": _ctx} if _ctx else card
            sim = runtime.create_session_from_data(
                scenario=scenario, characters={cid: turn_card}, api_key=sess.api_key,
            )
            # OPT-008 Cut 2: STREAM the turn — the avatar starts speaking at the first
            # sentence boundary while the rest of the reply is still generating; the rest
            # (tail synth, operator log, cleanup) finishes in the background. Falls through
            # to the blocking turn below ONLY if streaming failed before anything was pushed.
            streamed = await _stream_reply_turn(
                sess, sim.id, cid, scenario_id, text, persona_name)
            if streamed is not None:
                return JSONResponse(streamed)
            # take_turn makes a SYNCHRONOUS, blocking Anthropic call — run it OFF the event
            # loop, else it freezes the whole async portal (no avatar serving, no WS, no reply
            # for ANY client). Bounded so a slow/bad key surfaces as an error reply, not a hang.
            import asyncio
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(runtime.take_turn, sim.id, cid, text), timeout=25.0)
            except asyncio.TimeoutError:
                result = {"ok": False, "error": "character timed out"}
            runtime.end_session(sim.id)
            if result.get("ok"):
                reply = str(result.get("reply") or "").strip()
                mode = "ai"
            else:
                reply = f"(the character could not respond: {result.get('error')})"
                mode = "error"
        if not reply:
            reply = f"I heard you say: {text}"
            if mode != "error":
                mode = "echo"

        # From here, the voice synth + operator log use vsess (the bed we borrowed
        # in room mode; identical to sess in single-patient mode).
        sess = vsess

        # FR-009 H2 — feed the trainee's utterance to the off-going handoff
        # gap-tracker, keyed by the resolved encounter (the bed in room mode), so
        # the on-coming counterpart can probe what was NOT covered. (This ran
        # before `sess` was resolved previously, so it silently never fired.)
        if sess is not None:
            try:
                from . import handoff as _hg
                if _hg.get(sess.id):
                    _hg.note_student_utterance(sess.id, text)
            except Exception:  # noqa: BLE001
                pass

        # Surface the exchange in the OPERATOR's control transcript. The turn above
        # runs in a throwaway runtime session, so without this the operator never
        # sees device-voice input/replies. log_turn appends the student utterance +
        # the character reply (two entries) that /api/control/transcript serves.
        if sess is not None:
            try:
                sess.log_turn(
                    source=f"device:{cid}",
                    source_label=f"{persona_name} · device voice",
                    persona_id=cid,
                    persona_name=persona_name,
                    student_text=text,
                    character_text=reply,
                )
            except Exception:  # noqa: BLE001 — a logging hiccup must never fail the turn
                pass
            # FR-008 S3: stamp 'delivered' if a staged verbal error was spoken.
            from . import med_errors as _me, med_orders as _mo
            _me.note_character_reply(
                sess.id, cid, reply,
                role=_mo.role_kind(str((card or {}).get("role") or "")))

        # Voice the reply server-side in the operator-assigned ElevenLabs voice
        # (ADR-0031) so tablets that can't run the on-device ONNX TTS still speak;
        # falls back to a text-only frame (device built-in voice) when unset.
        #
        # OPT-008 Cut 1 (pipelined TTS): nothing used to play until the WHOLE reply was
        # synthesized. Now: split the reply at the first sentence boundary, synth + push
        # the FIRST chunk immediately (end_of_utterance=False), ack the POST, and synth +
        # push the remainder in a background task — the client's audio_pipeline plays
        # back-to-back frames gapless (playhead scheduling), so the avatar starts speaking
        # one sentence-synth after the LLM instead of after the full-reply synth. Falls
        # back to today's single frame whenever there's no usable split or no voice.
        first, rest = _split_reply(reply)
        audio_b64: str | None = None
        audio_format: str | None = None
        if rest:
            audio_b64, audio_format = await _synthesize_voice(sess, cid,first)
        if rest and audio_b64:
            spoken = await push_speech(scenario_id, cid, text=first,
                                       audio_b64=audio_b64, audio_format=audio_format,
                                       end_of_utterance=False)

            async def _push_tail() -> None:
                """Synth + push the remainder; on synth failure push it TEXT-ONLY so the
                turn is never half-silent (the device's built-in voice covers the tail)."""
                tail_b64: str | None = None
                tail_fmt: str | None = None
                try:
                    tail_b64, tail_fmt = await _synthesize_voice(sess, cid,rest)
                except Exception:  # noqa: BLE001 — fall through to the text-only frame
                    tail_b64, tail_fmt = None, None
                try:
                    await push_speech(scenario_id, cid, text=rest,
                                      audio_b64=tail_b64, audio_format=tail_fmt)
                except Exception:  # noqa: BLE001 — never crash the loop from a bg task
                    import logging
                    logging.getLogger(__name__).warning(
                        "OPT-008 tail push failed for %s", cid, exc_info=True)

            import asyncio as _aio
            t = _aio.create_task(_push_tail())
            _speech_tail_tasks.add(t)
            t.add_done_callback(_speech_tail_tasks.discard)
            return JSONResponse(
                {"ok": True, "heard": text, "reply": reply, "mode": mode,
                 "streamed": True, **spoken})

        # Single-frame path (short reply, no split, or no server voice) — unchanged.
        audio_b64, audio_format = await _synthesize_voice(sess, cid,reply)
        spoken = await push_speech(scenario_id, cid, text=reply,
                                   audio_b64=audio_b64, audio_format=audio_format)
        return JSONResponse(
            {"ok": True, "heard": text, "reply": reply, "mode": mode, **spoken})

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


# ── FACE ENGINE integration (request a synthetic face on demand) ─────────
# FACE ENGINE is the standalone synthetic-portrait service (default local :8790).
# The portal only sends what the card knows (ageRange/sex); FACE ENGINE derives the
# full demographic spec, generates + screens + signs the face, and delivers it as the
# standard drop-file — so resolve_portrait()/is_portrait_ai() pick it up unchanged.

FACE_ENGINE_URL = os.environ.get("FACE_ENGINE_URL", "http://127.0.0.1:8790")


async def request_face_from_engine(character_id: str,
                                   timeout_s: float = 60.0) -> dict[str, Any]:
    """Ask FACE ENGINE to generate this character's portrait; poll until delivered.
    Returns {"status": "done"|"failed"|"error", ...}. Never raises."""
    import asyncio

    import httpx

    card = resolve_card(character_id) or {}
    payload = {
        "character_id": character_id,
        "age_range": str(card.get("ageRange") or card.get("age") or "") or None,
        "sex": (card.get("sex") or None),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{FACE_ENGINE_URL}/api/vrai/request", json=payload)
            if resp.status_code == 401:
                return {"status": "error",
                        "error": "FACE ENGINE requires an operator token (RBAC enabled)"}
            resp.raise_for_status()
            request_id = resp.json()["request_id"]
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1.0)
                status = (await client.get(
                    f"{FACE_ENGINE_URL}/api/vrai/request/{request_id}")).json()
                if status.get("status") in ("done", "failed"):
                    return status
            return {"status": "error", "error": f"timed out after {timeout_s:.0f}s"}
    except Exception as exc:  # FACE ENGINE down/unreachable — surface, don't crash the portal
        return {"status": "error",
                "error": f"FACE ENGINE unreachable at {FACE_ENGINE_URL}: {exc}"}
