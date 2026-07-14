"""Text-to-speech providers — one interface, two transports (V8 gate 1b).

``TtsProvider.synthesize_stream(text, voice_id, api_key, language=...)`` is an async byte generator
with the SAME contract ``portal.voices.synthesize_stream`` established: raises ``ValueError`` on bad
input and ``httpx`` errors on transport failure — both consuming routes (the avatar's
``_synthesize_voice`` and the station-facing ``/api/tts``) catch those and fall back to the device's
built-in voice, so a provider swap cannot change the failure UX. Both providers emit mp3.

Selection is by env, default = today's stack (ElevenLabs), so this is INERT until a provider is chosen:
    TTS_PROVIDER = elevenlabs | azure          (make_tts)

THE VOICE RE-CAST IS CONFIG, NOT CODE. The 37 persona voices are ElevenLabs IP — non-portable — so any
alternate provider needs a casting decision: which of ITS voices plays each persona. That decision lives
in ``portal/data/azure_voice_map.json`` ({elevenlabs_voice_id: azure_voice_name}, ``_default`` for
anything unmapped, env ``AZURE_TTS_DEFAULT_VOICE`` overrides the default). The bake-off that fills the
map in happens during the provider-validation run (Task #54) once Azure credentials exist; until then
every persona speaks the default Azure voice — correct plumbing, placeholder casting.

Azure credentials are org-wide env config (``AZURE_SPEECH_KEY`` / ``AZURE_SPEECH_REGION``), matching how
a Gov/DoD deployment is provisioned — NOT the per-session ElevenLabs key (which the ElevenLabs provider
keeps using unchanged). ``AZURE_SPEECH_ENDPOINT_SUFFIX=tts.speech.azure.us`` switches to Azure Government.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

_VOICE_MAP_PATH = Path(__file__).parent.parent / "data" / "azure_voice_map.json"
_DEFAULT_AZURE_VOICE = "en-US-JennyNeural"


class TtsProvider(Protocol):
    name: str
    label: str  # engine identifier recorded in logs/headers

    def available(self) -> bool: ...
    def synthesize_stream(
        self, text: str, voice_id: str, api_key: str, *, language: str | None = None
    ) -> AsyncIterator[bytes]: ...


class ElevenLabsTts:
    """Today's production path — a thin delegate to ``portal.voices.synthesize_stream`` so behavior
    (per-session key, Flash v2.5, streaming-latency params, MAX_TTS_CHARS truncation) is byte-identical."""

    name = "elevenlabs"
    label = "elevenlabs/flash-v2.5"

    def available(self) -> bool:
        # Availability for ElevenLabs is the caller's key check (per-session vault key) — the existing
        # call sites gate on the key before synthesizing, unchanged.
        return True

    def synthesize_stream(
        self, text: str, voice_id: str, api_key: str, *, language: str | None = None
    ) -> AsyncIterator[bytes]:
        from portal import voices

        return voices.synthesize_stream(text, voice_id, api_key, language=language)


def _load_voice_map() -> dict[str, str]:
    """The ElevenLabs-voice-id -> Azure-voice-name casting map. Missing/invalid file = empty map (every
    voice falls back to the default) — the plumbing must work before the bake-off fills the map in."""
    try:
        data = json.loads(_VOICE_MAP_PATH.read_text())
        return {
            k: str(v)
            for k, v in data.items()
            if isinstance(v, str) and not k.startswith("_comment")
        }
    except Exception:  # noqa: BLE001 — an unreadable map is "no casting yet", never an error
        return {}


class AzureTts:
    """Azure AI Speech (neural TTS) via the REST synthesis endpoint — the managed-TTS path for Azure
    commercial and Azure Government (the primary IL5 managed TTS per the landscape study)."""

    name = "azure"

    def __init__(self, key: str, region: str, endpoint_suffix: str, default_voice: str) -> None:
        self._key = key or ""
        self._region = region or ""
        self._suffix = endpoint_suffix or "tts.speech.microsoft.com"
        self._default_voice = default_voice or _DEFAULT_AZURE_VOICE
        self._map = _load_voice_map()

    @property
    def label(self) -> str:
        return f"azure/{self._region or 'unconfigured'}"

    def available(self) -> bool:
        return bool(self._key and self._region)

    def map_voice(self, voice_id: str) -> str:
        """ElevenLabs voice id -> cast Azure voice; unmapped (or empty) -> the default voice."""
        mapped = self._map.get((voice_id or "").strip(), "")
        if mapped:
            return mapped
        return self._map.get("_default", "") or self._default_voice

    async def synthesize_stream(
        self, text: str, voice_id: str, api_key: str, *, language: str | None = None
    ) -> AsyncIterator[bytes]:
        # Same input contract as voices.synthesize_stream: ValueError on bad input so the routes'
        # fallback handling is identical. `api_key` (the ElevenLabs session key) is ignored — Azure
        # credentials are org-wide env config by design.
        from portal import voices

        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        if not self.available():
            raise ValueError("Azure Speech not configured (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)")
        if len(text) > voices.MAX_TTS_CHARS:
            text = text[: voices.MAX_TTS_CHARS]

        voice = self.map_voice(voice_id)
        lang = language or "-".join(voice.split("-")[:2]) or "en-US"
        # Minimal XML escaping for the SSML text node.
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        ssml = f"<speak version='1.0' xml:lang='{lang}'><voice name='{voice}'>{esc}</voice></speak>"
        url = f"https://{self._region}.{self._suffix}/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "medsim-v8",
        }

        import httpx

        client = _azure_client()
        async with client.stream(
            "POST", url, content=ssml.encode("utf-8"), headers=headers
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:300].decode("utf-8", "replace")
                raise httpx.HTTPStatusError(
                    f"Azure TTS {resp.status_code}: {detail}",
                    request=resp.request,
                    response=resp,
                )
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk


_client_singleton: Any = None


def _azure_client():
    """Persistent async client (mirrors voices._async_client) so back-to-back turns skip the TLS
    handshake — the same ~200 ms latency-budget reasoning as the ElevenLabs path."""
    global _client_singleton
    if _client_singleton is None:
        import httpx

        _client_singleton = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=6.0))
    return _client_singleton


def make_tts() -> TtsProvider:
    """Select the TTS provider from TTS_PROVIDER (default elevenlabs -> today's stack, inert)."""
    provider = (os.environ.get("TTS_PROVIDER", "") or "elevenlabs").lower()
    if provider == "azure":
        return AzureTts(
            os.environ.get("AZURE_SPEECH_KEY", ""),
            os.environ.get("AZURE_SPEECH_REGION", ""),
            os.environ.get("AZURE_SPEECH_ENDPOINT_SUFFIX", "") or "tts.speech.microsoft.com",
            os.environ.get("AZURE_TTS_DEFAULT_VOICE", "") or _DEFAULT_AZURE_VOICE,
        )
    return ElevenLabsTts()
