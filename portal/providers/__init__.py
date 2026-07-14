"""Swappable AI providers behind one seam (V8 gate 1 — mirrors the V9 provider-adapters pattern).

The character prompts + turn-building logic live in ``portal.runtime`` and are IDENTICAL across
vendors — only the transport (which API is called) changes here. That is the whole point: a DoD site
where Claude is not procurable (Anthropic is FASCSA-excluded from DoD contracts as of 2026) becomes a
config flip, not a rewrite.

Selection is by env, defaults = today's stack (Anthropic keyed per-session from the operator's vault;
ElevenLabs voices), so this is INERT until a provider is chosen:
    LLM_PROVIDER = anthropic | azure_openai | bedrock   (chat.make_chat)
    TTS_PROVIDER = elevenlabs | azure                   (tts.make_tts)

The TTS voice re-cast is CONFIG, not code: the 37 persona voices are ElevenLabs IP (non-portable), so
an alternate provider's casting lives in ``portal/data/azure_voice_map.json`` — filled in during the
provider-validation bake-off (Task #54), with a default voice until then. See ``tts.py``.

STT is deliberately NOT adapted: V8's STT (faster-whisper) is already local and zero-cost — exactly
right for the on-prem/air-gap posture — and the primary student-injection path
(``/api/face/{id}/listen``) bypasses STT entirely. The cloud/DoD STT swap is V9's job (its adapter is
merged there).
"""

from .chat import AnthropicChat, AzureOpenAIChat, BedrockChat, ChatProvider, make_chat
from .tts import AzureTts, ElevenLabsTts, TtsProvider, make_tts

__all__ = [
    "ChatProvider",
    "AnthropicChat",
    "AzureOpenAIChat",
    "BedrockChat",
    "make_chat",
    "TtsProvider",
    "ElevenLabsTts",
    "AzureTts",
    "make_tts",
]
