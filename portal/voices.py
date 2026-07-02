"""MEDSIM V4 — ElevenLabs neural TTS voice service.

Synthesizes character speech with the **eleven_flash_v2_5** model — the
low-latency model (~75 ms inference) that holds perceived latency near
200 ms when paired with the streaming endpoint.

Design principles:

- **Graceful degradation.** Every public function has a no-throw path.
  When ElevenLabs is unreachable (no key, offline, error) the system
  falls back to the V2/V3 browser SpeechSynthesis path. `voices.py`
  never raises into a request handler.
- **Catalog: live preferred, static fallback.** `list_voices()` fetches
  the operator's ElevenLabs `/v1/voices` and caches it; if that fails it
  returns the bundled static catalog so voice selection still works.
- **Key resolution order** (see CLAUDE.md): vault credential →
  env var ELEVENLABS_API_KEY → ~/.medsim/elevenlabs.key.

Public surface:
    get_api_key(vault=None)            -> str
    is_configured(vault=None)          -> bool
    health(api_key)                    -> dict
    list_voices(api_key)               -> {"voices": [...], "source": ...}
    candidates_for(persona, api_key)   -> list[voice]  (<=5)
    synthesize_stream(text, voice_id, api_key)  -> async byte generator
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator

DATA_DIR = Path(__file__).resolve().parent / "data"
KEYFILE = Path.home() / ".medsim" / "elevenlabs.key"

API_BASE = "https://api.elevenlabs.io"
MODEL = "eleven_flash_v2_5"           # low-latency model — see CLAUDE.md
OUTPUT_FORMAT = "mp3_44100_128"
OPTIMIZE_LATENCY = 3                  # 0-4; 3 is a good latency/quality balance
HTTP_TIMEOUT = 12.0
CATALOG_TTL = 600.0                   # seconds to cache a live /v1/voices fetch

# Cost guardrail — never send an absurd amount of text to TTS in one call.
MAX_TTS_CHARS = 1200

# FR-020: `*stage direction*` spans are kept in the reply DATA (TurnRecord, frames,
# operator log — the avatar's autoEmote/animation reads them) but must never be
# SPOKEN. This is the canonical strip, applied at every synthesis boundary
# (server ElevenLabs paths here + the client speak fallbacks mirror it in JS/TS).
_STAGE_DIRECTION_RE = re.compile(r"\*[^*]*\*")


def strip_stage_directions(text: str) -> str:
    """Return `text` with `*stage direction*` spans removed, for TTS input ONLY.

    Unbalanced stars → returned unchanged (conservative, mirrors _split_reply's
    fallback — never risk eating real dialog). Returns '' for a direction-only
    line; callers then skip voicing entirely (silence + on-screen note, no
    device-voice fallback reading the note aloud)."""
    if "*" not in text:
        return text
    if text.count("*") % 2:
        return text
    out = _STAGE_DIRECTION_RE.sub(" ", text)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,!?;:])", r"\1", out)
    return out.strip()


# ──────────────────────────────────────────────────────────────────────
# Key resolution
# ──────────────────────────────────────────────────────────────────────

# Once the key has been resolved from the vault by any operator-authed
# route, it is cached here so station-facing routes (and the legacy V1
# voice session, which has no ControlSession) can synthesize too.
_runtime_key: str = ""


def get_api_key(vault: Any | None = None) -> str:
    """Resolve the ElevenLabs API key. Order: vault → env → keyfile →
    runtime cache (a key seen on a prior resolution).

    `vault` is the unlocked credentials.Vault when called from an
    operator-authenticated route; omitted for station routes.
    """
    global _runtime_key
    if vault is not None:
        try:
            v = vault.get("ELEVENLABS_API_KEY")
            if v:
                _runtime_key = v.strip()
                return _runtime_key
        except Exception:  # noqa: BLE001
            pass
    env = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if env:
        _runtime_key = env
        return env
    try:
        if KEYFILE.exists():
            k = KEYFILE.read_text().strip()
            if k:
                _runtime_key = k
                return k
    except OSError:
        pass
    # Last resort — a key resolved earlier this process lifetime.
    return _runtime_key


def is_configured(vault: Any | None = None) -> bool:
    return bool(get_api_key(vault))


# ──────────────────────────────────────────────────────────────────────
# Static data — fallback catalog + persona traits
# ──────────────────────────────────────────────────────────────────────

_fallback_cache: list[dict[str, Any]] | None = None
_traits_cache: dict[str, Any] | None = None


def _fallback_catalog() -> list[dict[str, Any]]:
    global _fallback_cache
    if _fallback_cache is None:
        try:
            doc = json.loads((DATA_DIR / "elevenlabs_fallback_voices.json").read_text())
            _fallback_cache = [_normalize_voice(v, source="fallback")
                               for v in doc.get("voices", [])]
        except (OSError, json.JSONDecodeError):
            _fallback_cache = []
    return _fallback_cache


def _traits_doc() -> dict[str, Any]:
    global _traits_cache
    if _traits_cache is None:
        try:
            _traits_cache = json.loads((DATA_DIR / "persona_voice_traits.json").read_text())
        except (OSError, json.JSONDecodeError):
            _traits_cache = {"traits": {}, "ethnicity_to_accents": {}}
    return _traits_cache


def persona_traits(persona_id: str) -> dict[str, Any]:
    """Return {sex, age_band, accent, ethnicity, language} for a persona,
    with safe defaults for unknown ids."""
    t = _traits_doc().get("traits", {}).get(persona_id)
    if t:
        return dict(t)
    return {"sex": "U", "age_band": "middle_aged", "accent": "american",
            "ethnicity": "anglo_american", "language": "en"}


# ──────────────────────────────────────────────────────────────────────
# Voice normalization
# ──────────────────────────────────────────────────────────────────────

def _normalize_voice(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Bring a voice dict (live API or fallback file) into one shape:
    {voice_id, name, gender, age, accent, descriptive, preview_url, source}.
    """
    labels = raw.get("labels") or {}
    gender = (raw.get("gender") or labels.get("gender") or "").lower()
    age = (raw.get("age") or labels.get("age") or "").lower().replace(" ", "_")
    accent = (raw.get("accent") or labels.get("accent") or "").lower()
    descriptive = (raw.get("descriptive") or labels.get("descriptive")
                   or labels.get("description") or "").lower()
    return {
        "voice_id":    raw.get("voice_id") or raw.get("id") or "",
        "name":        raw.get("name") or "Voice",
        "gender":      gender or "neutral",
        "age":         age or "middle_aged",
        "accent":      accent or "american",
        "descriptive": descriptive,
        "preview_url": raw.get("preview_url") or "",
        "source":      source,
    }


# ──────────────────────────────────────────────────────────────────────
# Catalog — live fetch with cache + static fallback
# ──────────────────────────────────────────────────────────────────────

_catalog_cache: dict[str, Any] = {"key_hash": None, "fetched_at": 0.0, "voices": None}


def list_voices(api_key: str = "") -> dict[str, Any]:
    """Return {"voices": [...normalized...], "source": "live"|"fallback",
    "detail": str}. Never raises."""
    if not api_key:
        return {"voices": _fallback_catalog(), "source": "fallback",
                "detail": "No ElevenLabs key configured."}

    key_hash = hash(api_key)
    now = time.time()
    if (_catalog_cache["voices"] is not None
            and _catalog_cache["key_hash"] == key_hash
            and (now - _catalog_cache["fetched_at"]) < CATALOG_TTL):
        return {"voices": _catalog_cache["voices"], "source": "live",
                "detail": "cached"}

    try:
        import httpx
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get(f"{API_BASE}/v1/voices",
                               headers={"xi-api-key": api_key})
        if resp.status_code != 200:
            return {"voices": _fallback_catalog(), "source": "fallback",
                    "detail": f"ElevenLabs /v1/voices returned {resp.status_code}."}
        raw_voices = resp.json().get("voices", [])
        voices = [_normalize_voice(v, source="live") for v in raw_voices if v.get("voice_id")]
        if not voices:
            return {"voices": _fallback_catalog(), "source": "fallback",
                    "detail": "Live catalog was empty."}
        _catalog_cache.update(key_hash=key_hash, fetched_at=now, voices=voices)
        return {"voices": voices, "source": "live", "detail": f"{len(voices)} voices"}
    except Exception as exc:  # noqa: BLE001
        return {"voices": _fallback_catalog(), "source": "fallback",
                "detail": f"Live fetch failed ({type(exc).__name__}); using fallback catalog."}


def health(api_key: str = "") -> dict[str, Any]:
    """Quick availability probe. Never raises."""
    if not api_key:
        return {"available": False, "source": "fallback",
                "detail": "ElevenLabs key not configured — browser voices in use.",
                "voice_count": len(_fallback_catalog())}
    cat = list_voices(api_key)
    live = cat["source"] == "live"
    return {
        "available":   live,
        "source":      cat["source"],
        "detail":      cat["detail"],
        "voice_count": len(cat["voices"]),
        "model":       MODEL,
    }


# ──────────────────────────────────────────────────────────────────────
# Candidate selection — 5 voices per persona by sex / age / ethnicity
# ──────────────────────────────────────────────────────────────────────

_AGE_ORDER = ["child", "young", "middle_aged", "old"]


def _age_distance(persona_band: str, voice_age: str) -> int:
    """0 = exact, 1 = adjacent, 2 = far. child maps onto young."""
    pb = "young" if persona_band == "child" else persona_band
    va = "young" if voice_age in ("child", "") else voice_age
    try:
        return abs(_AGE_ORDER.index(pb) - _AGE_ORDER.index(va))
    except ValueError:
        return 2


def candidates_for(persona_id: str, api_key: str = "", n: int = 5) -> dict[str, Any]:
    """Return up to `n` candidate voices for a 24-library persona."""
    out = candidates_by_traits(persona_traits(persona_id), api_key, n)
    out["persona_id"] = persona_id
    return out


def candidates_by_traits(traits: dict[str, Any], api_key: str = "",
                          n: int = 5) -> dict[str, Any]:
    """Return up to `n` candidate voices for an arbitrary character, ranked
    by how well they match the given sex / age band / ethnicity / accent.

    Used both by `candidates_for` (24-persona library) and the legacy V1
    voice session (whose characters carry only a voice profile, no
    persona id). Returns {"traits", "source", "detail", "candidates"}.
    """
    traits = dict(traits or {})
    traits.setdefault("sex", "U")
    traits.setdefault("age_band", "middle_aged")
    traits.setdefault("accent", "american")
    traits.setdefault("ethnicity", "anglo_american")

    cat = list_voices(api_key)
    voices = cat["voices"]

    sex = (traits.get("sex") or "U").upper()
    persona_band = traits.get("age_band", "middle_aged")
    ethnicity = traits.get("ethnicity", "")
    accent_pref = set(
        _traits_doc().get("ethnicity_to_accents", {}).get(ethnicity, [])
    )
    accent_pref.add(traits.get("accent", ""))

    sex_to_gender = {"F": "female", "M": "male"}
    want_gender = sex_to_gender.get(sex)  # None when persona sex is "U"

    def score(v: dict[str, Any]) -> tuple[int, int]:
        s = 0
        # Gender — strongest signal.
        if want_gender:
            if v["gender"] == want_gender:
                s += 10
            elif v["gender"] == "neutral":
                s += 3
            # opposite gender: no points (still eligible if pool is thin)
        else:
            s += 4  # persona sex unknown — any gender acceptable
        # Age band.
        ad = _age_distance(persona_band, v["age"])
        s += {0: 6, 1: 3}.get(ad, 0)
        # Accent / ethnicity soft match.
        if v["accent"] in accent_pref:
            s += 4
        if v["accent"] == traits.get("accent"):
            s += 2
        # Child personas prefer a youthful/childish descriptive.
        if persona_band == "child" and "child" in v["descriptive"]:
            s += 5
        # Tie-breaker: stable by name length then name.
        return (s, -len(v["name"]))

    ranked = sorted(voices, key=score, reverse=True)
    return {
        "traits":     traits,
        "source":     cat["source"],
        "detail":     cat["detail"],
        "candidates": ranked[:n],
    }


# ──────────────────────────────────────────────────────────────────────
# Synthesis — streaming, Flash v2.5
# ──────────────────────────────────────────────────────────────────────

async def synthesize_stream(
    text: str,
    voice_id: str,
    api_key: str,
    *,
    model: str = MODEL,
    language: str | None = None,
) -> AsyncIterator[bytes]:
    """Async generator yielding mp3 chunks from ElevenLabs Flash v2.5.

    Raises ValueError on bad input and httpx errors on transport failure
    — the *route* catches these and signals the client to fall back to
    browser TTS. (Keeping the raise here means the route can distinguish
    'fall back' from 'empty audio'.)
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")
    if not voice_id:
        raise ValueError("no voice_id")
    if not api_key:
        raise ValueError("no api_key")
    if len(text) > MAX_TTS_CHARS:
        text = text[:MAX_TTS_CHARS]

    import httpx
    url = f"{API_BASE}/v1/text-to-speech/{voice_id}/stream"
    params = {
        "optimize_streaming_latency": str(OPTIMIZE_LATENCY),
        "output_format": OUTPUT_FORMAT,
    }
    body: dict[str, Any] = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "use_speaker_boost": True,
        },
    }
    if language:
        # Flash v2.5 accepts an optional language_code hint.
        body["language_code"] = language

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    # Reuse a persistent client so back-to-back turns skip the TLS
    # handshake — material for the ~200 ms latency budget.
    client = _async_client()
    async with client.stream("POST", url, params=params,
                              json=body, headers=headers) as resp:
        if resp.status_code != 200:
            detail = (await resp.aread())[:300].decode("utf-8", "replace")
            raise httpx.HTTPStatusError(
                f"ElevenLabs TTS {resp.status_code}: {detail}",
                request=resp.request, response=resp,
            )
        async for chunk in resp.aiter_bytes():
            if chunk:
                yield chunk


_shared_async_client: Any | None = None


def _async_client():
    """Lazily build a process-wide httpx.AsyncClient with keep-alive so
    repeated TTS calls reuse the TLS connection to ElevenLabs."""
    global _shared_async_client
    if _shared_async_client is None:
        import httpx
        _shared_async_client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120.0),
        )
    return _shared_async_client
