"""Swappable LLM providers behind one seam (V8 gate 1 — mirrors the V9 provider-adapters pattern).

The character prompts + turn-building logic live in ``portal.runtime`` and are IDENTICAL across
vendors — only the transport (which API is called) changes here. That is the whole point: a DoD site
where Claude is not procurable (Anthropic is FASCSA-excluded from DoD contracts as of 2026) becomes a
config flip, not a rewrite.

Selection is by env, default = today's stack (Anthropic, keyed per-session from the operator's vault —
unchanged), so this is INERT until a provider is chosen:
    LLM_PROVIDER = anthropic | azure_openai | bedrock   (chat.make_chat)

Scope note: only the LLM is adapted here. TTS stays ElevenLabs-only in this pass — V8's TTS is coupled
to the ElevenLabs voice CATALOG (voice_id lookup, trait-matched candidates), and swapping it needs a
voice re-cast decision (which Azure/Cartesia voice maps to which of the 37 personas) that is a product
call, not a plumbing change. STT is untouched: V8's STT (faster-whisper) is already local/zero-cost, and
the primary student-injection path (/api/face/{id}/listen) bypasses STT entirely.
"""

from .chat import AnthropicChat, AzureOpenAIChat, BedrockChat, ChatProvider, make_chat

__all__ = ["ChatProvider", "AnthropicChat", "AzureOpenAIChat", "BedrockChat", "make_chat"]
