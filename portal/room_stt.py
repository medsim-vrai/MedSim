# Room-local STT (ADR-0038, FR-006b). The instructor's Mac transcribes for the
# low-cost audio-only stations: the tablet POSTs its recorded 16 kHz mono float32
# PCM here and gets text back in well under a second — from a BIGGER model
# (small.en vs the tablets' tiny.en) than that hardware could ever run.
#
# PHI boundary (instructor-ratified 2026-06-11): trainee audio may cross the
# room's LAN to THIS portal over TLS and to no other destination. The buffer is
# transcribed in memory and discarded — never written to disk, never logged,
# never forwarded. Cloud STT for teaching use stays prohibited (ADR-0014/0025).
#
# Engine: faster-whisper (CTranslate2, MIT), lazy singleton, loaded off the event
# loop. A daemon thread warms it at attach() so the first take doesn't pay the
# ~2 s load (skip with MEDSIM_STT_WARM=0). Model size via MEDSIM_STT_MODEL.

from __future__ import annotations

import asyncio
import hmac
import os
import threading
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 4                                   # float32 PCM
_MIN_BYTES = int(0.25 * SAMPLE_RATE) * _BYTES_PER_SAMPLE   # <0.25 s → too short
_MAX_BYTES = 30 * SAMPLE_RATE * _BYTES_PER_SAMPLE          # >30 s → reject (PTT clips)


def model_name() -> str:
    return (os.environ.get("MEDSIM_STT_MODEL") or "").strip() or "small.en"


_engine: Any = None
_engine_err: str | None = None
_engine_lock = threading.Lock()


def _load_engine() -> Any:
    """Lazy singleton; blocking (call off the event loop). Returns None on failure."""
    global _engine, _engine_err
    with _engine_lock:
        if _engine is not None or _engine_err is not None:
            return _engine
        try:
            t0 = time.perf_counter()
            from faster_whisper import WhisperModel  # heavy import — keep lazy
            _engine = WhisperModel(model_name(), device="cpu", compute_type="int8")
            print(f"[room-stt] {model_name()} ready in {time.perf_counter() - t0:.1f}s "
                  f"(room-local transcription, ADR-0038)")
        except Exception as e:  # noqa: BLE001 — engine absence must not kill the portal
            _engine_err = f"{type(e).__name__}: {e}"
            print(f"[room-stt] engine unavailable: {_engine_err}")
        return _engine


def _transcribe(pcm: bytes) -> str:
    """Blocking transcription of raw 16 kHz mono float32 PCM (call off the event loop)."""
    engine = _load_engine()
    if engine is None:
        raise RuntimeError(_engine_err or "engine unavailable")
    import numpy as np  # faster-whisper dependency, present iff the engine is
    audio = np.frombuffer(pcm, dtype=np.float32)
    segments, _info = engine.transcribe(
        audio,
        language="en",
        beam_size=1,                       # PTT clips are short — greedy is plenty
        vad_filter=True,                   # trim leading/trailing button-press silence
        condition_on_previous_text=False,  # takes are independent utterances
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def warm_in_background() -> None:
    if (os.environ.get("MEDSIM_STT_WARM") or "1").strip() == "0":
        return
    threading.Thread(target=_load_engine, name="room-stt-warm", daemon=True).start()


def attach(app: FastAPI) -> None:
    @app.post("/api/face/stt")
    async def api_face_stt(request: Request):  # noqa: ANN202
        """Device-facing transcription (same trust posture as /listen — no auth by
        default, ADR-0027 device token enforced when MEDSIM_FACE_TOKEN is set).
        Body: raw 16 kHz mono float32 PCM. The audio is transcribed in memory and
        discarded — by design nothing here logs or stores it (ADR-0038)."""
        from . import vrai_faces

        if vrai_faces.token_enabled():
            scenario = str(request.query_params.get("scenario") or "default")
            character = str(request.query_params.get("character") or "")
            token = str(request.query_params.get("token") or "")
            if not hmac.compare_digest(
                    token, vrai_faces.face_token(scenario, character)):
                return JSONResponse({"ok": False, "error": "invalid device token"},
                                    status_code=403)

        body = await request.body()
        if len(body) > _MAX_BYTES:
            return JSONResponse({"ok": False, "error": "clip too long (>30s)"},
                                status_code=413)
        if len(body) < _MIN_BYTES or len(body) % _BYTES_PER_SAMPLE != 0:
            return JSONResponse(
                {"ok": False, "error": "body must be ≥0.25s of 16kHz mono float32 PCM"},
                status_code=400)

        t0 = time.perf_counter()
        try:
            text = await asyncio.to_thread(_transcribe, bytes(body))
        except RuntimeError as e:
            return JSONResponse({"ok": False, "error": f"STT engine unavailable: {e}"},
                                status_code=503)
        except Exception as e:  # noqa: BLE001 — malformed PCM etc.
            return JSONResponse({"ok": False, "error": f"transcription failed: {e}"},
                                status_code=500)
        return JSONResponse({
            "ok": True,
            "text": text,
            "ms": int((time.perf_counter() - t0) * 1000),
            "model": model_name(),
        })
