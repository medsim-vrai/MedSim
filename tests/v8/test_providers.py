"""V8 gate 1 — swappable LLM providers.

Proves: (1) LLM_PROVIDER selects the transport, default unset == today's Anthropic-per-session-key
behavior, byte-for-byte; (2) runtime.take_turn/take_instructor_line/take_turn_stream are provider-
agnostic — the SAME system prompt + messages reach whichever provider is selected; (3) the existing
friendly-error UX for a rejected Anthropic key is unchanged; (4) Azure OpenAI + Bedrock construct the
right request shape and are otherwise inert (no env set = unreachable, never called)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from portal import readiness, runtime
from portal.providers import tts as tts_mod
from portal.providers.chat import AnthropicChat, AzureOpenAIChat, BedrockChat, make_chat
from portal.providers.tts import AzureTts, ElevenLabsTts, make_tts


@pytest.fixture(autouse=True)
def _isolated_key_verdict():
    """runtime._note_key() writes real FR-128 telemetry into readiness._key_verdict — a few tests
    here deliberately exercise that path (proving the seam preserves it), which would otherwise
    leak into test_readiness.py's assumptions about the verdict's starting state. Save/restore."""
    before = dict(readiness._key_verdict)
    yield
    readiness._key_verdict.clear()
    readiness._key_verdict.update(before)


def _session():
    return runtime.create_session_from_data(
        scenario={"id": "ENC1", "name": "Case", "patient": {}},
        characters={"P-1": {"id": "P-1", "name": "Pat", "role": "patient"}},
        api_key="sk-test-session-key",
    )


# --- make_chat selection ------------------------------------------------------------------------


def test_default_provider_is_anthropic_keyed_by_session(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    chat = make_chat(session_api_key="sk-abc", model="claude-haiku-4-5")
    assert isinstance(chat, AnthropicChat)
    assert chat.label == "claude-haiku-4-5"
    assert chat._key == "sk-abc"  # the OPERATOR'S session key, not an env-wide one


def test_llm_provider_env_selects_azure_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://res.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "azkey")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")
    chat = make_chat(session_api_key="sk-ignored", model="claude-haiku-4-5")
    assert isinstance(chat, AzureOpenAIChat)
    assert chat.label == "azure/gpt-5-mini"


def test_llm_provider_env_selects_bedrock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("BEDROCK_REGION", "us-gov-west-1")
    chat = make_chat(session_api_key="sk-ignored", model="claude-haiku-4-5")
    assert isinstance(chat, BedrockChat)
    assert chat.label == "bedrock/amazon.nova-lite-v1:0"


def test_unknown_provider_falls_back_to_anthropic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-vendor")
    chat = make_chat(session_api_key="sk-abc", model="m")
    assert isinstance(chat, AnthropicChat)


# --- provider-agnostic prompt building (runtime.py never changes per-vendor) --------------------


@pytest.fixture
def stub_anthropic(monkeypatch):
    """Stub anthropic.Anthropic exactly like the existing test suite does — proves the NEW seam
    reaches the same SDK call shape the OLD inline code did."""
    seen: dict = {}

    class _Resp:
        content = [type("B", (), {"type": "text", "text": "the reply"})()]

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            return _Resp()

    class _Client:
        def __init__(self, **kw):
            seen["client_kwargs"] = kw
            self.messages = _Msgs()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _Client)
    return seen


def test_take_turn_still_calls_anthropic_with_session_key(stub_anthropic):
    s = _session()
    out = runtime.take_turn(s.id, "P-1", "hello")
    assert out["ok"] is True
    assert out["reply"] == "the reply"
    assert stub_anthropic["client_kwargs"] == {"api_key": "sk-test-session-key"}
    assert stub_anthropic["model"] == runtime.MODEL
    assert stub_anthropic["max_tokens"] == runtime.MAX_TOKENS
    assert stub_anthropic["system"]  # a real system prompt was built, unchanged


def test_take_turn_reaches_identical_prompt_regardless_of_provider(monkeypatch, stub_anthropic):
    """Swap in a recording fake ChatProvider via make_chat and confirm runtime passes the exact
    same system/messages/max_tokens it always did — the seam adds a provider choice, not a prompt
    change."""
    seen: dict = {}

    class _Recording:
        name = "recording"
        label = "recording"

        def complete(self, *, system, messages, max_tokens):
            seen.update(system=system, messages=messages, max_tokens=max_tokens)
            return "recorded reply"

    monkeypatch.setattr(runtime, "make_chat", lambda **kw: _Recording())
    s = _session()
    out = runtime.take_turn(s.id, "P-1", "how are you?")
    assert out["ok"] is True and out["reply"] == "recorded reply"
    assert seen["max_tokens"] == runtime.MAX_TOKENS
    assert seen["system"]
    assert seen["messages"][-1] == {"role": "user", "content": "how are you?"}


def test_take_instructor_line_uses_the_same_seam(monkeypatch):
    seen: dict = {}

    class _Recording:
        name = "recording"
        label = "recording"

        def complete(self, *, system, messages, max_tokens):
            seen.update(system=system, messages=messages)
            return "in-character line"

    monkeypatch.setattr(runtime, "make_chat", lambda **kw: _Recording())
    s = _session()
    out = runtime.take_instructor_line(s.id, "P-1", "tell them you are in pain")
    assert out["ok"] is True and out["reply"] == "in-character line"
    assert "STAGE DIRECTION" in seen["messages"][-1]["content"]


def test_take_turn_stream_uses_the_seam_and_yields_deltas(monkeypatch):
    class _Recording:
        name = "recording"
        label = "recording"

        def stream(self, *, system, messages, max_tokens):
            yield "Hello"
            yield " there."

    monkeypatch.setattr(runtime, "make_chat", lambda **kw: _Recording())
    s = _session()
    gen = runtime.take_turn_stream(s.id, "P-1", "hi")
    parts = list(gen)
    assert parts == ["Hello", " there."]
    assert s.history[-1].character_response == "Hello there."


# --- error UX is unchanged for the default (Anthropic) provider ---------------------------------


def test_rejected_key_error_message_is_unchanged(monkeypatch):
    class _AuthErr(Exception):
        pass

    class _Recording:
        name = "recording"
        label = "recording"

        def complete(self, *, system, messages, max_tokens):
            raise _AuthErr("Error code: 401 - invalid x-api-key")

    monkeypatch.setattr(runtime, "make_chat", lambda **kw: _Recording())
    s = _session()
    out = runtime.take_turn(s.id, "P-1", "hello")
    assert out["ok"] is False
    assert "Anthropic API key was rejected" in out["error"]


# --- Azure OpenAI request shape -------------------------------------------------------------------


def test_azure_openai_complete_builds_the_right_request(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "az reply"}}]}

    def _fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json)
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)
    chat = AzureOpenAIChat("https://res.openai.azure.com", "azkey", "gpt-5-mini", "2024-10-21")
    out = chat.complete(
        system="be terse", messages=[{"role": "user", "content": "hi"}], max_tokens=50
    )
    assert out == "az reply"
    assert "gpt-5-mini" in captured["url"] and "2024-10-21" in captured["url"]
    assert captured["headers"]["api-key"] == "azkey"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "be terse"}
    # Azure has no native streaming here — stream() falls back to one chunk of complete().
    assert list(
        chat.stream(system="s", messages=[{"role": "user", "content": "hi"}], max_tokens=10)
    ) == ["az reply"]


# --- Bedrock — lazy-imported optional dependency (not installed in this venv) -------------------


def test_bedrock_complete_uses_a_lazily_imported_boto3(monkeypatch):
    """boto3 is NOT a hard dependency (mirrors V9's gate-1 pattern) — inject a fake module so the
    lazy `import boto3` inside complete() resolves without installing the real SDK."""
    calls = {}

    class _FakeBody:
        def read(self):
            import json

            return json.dumps({"content": [{"text": "bedrock reply"}]}).encode()

    class _FakeBedrockClient:
        def invoke_model(self, *, modelId, body):
            calls.update(modelId=modelId, body=body)
            return {"body": _FakeBody()}

    fake_boto3 = SimpleNamespace(client=lambda service, region_name: _FakeBedrockClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    chat = BedrockChat("anthropic.claude-haiku-4-5-20251001-v1:0", "us-gov-west-1")
    out = chat.complete(system="s", messages=[{"role": "user", "content": "hi"}], max_tokens=40)
    assert out == "bedrock reply"
    assert calls["modelId"] == "anthropic.claude-haiku-4-5-20251001-v1:0"


# =================================================================================================
# TTS providers (gate 1b) — TTS_PROVIDER selects the engine; default = ElevenLabs, byte-identical.
# =================================================================================================


def test_make_tts_default_is_elevenlabs_and_delegates(monkeypatch):
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    tts = make_tts()
    assert isinstance(tts, ElevenLabsTts)

    seen = {}
    sentinel = object()

    def _fake_synth(text, voice_id, api_key, *, language=None):
        seen.update(text=text, voice_id=voice_id, api_key=api_key, language=language)
        return sentinel

    from portal import voices

    monkeypatch.setattr(voices, "synthesize_stream", _fake_synth)
    out = tts.synthesize_stream("hello", "v-1", "el-key", language="en")
    assert out is sentinel  # a pure delegate — same generator object, same behavior
    assert seen == {"text": "hello", "voice_id": "v-1", "api_key": "el-key", "language": "en"}


def test_tts_provider_env_selects_azure(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_SPEECH_KEY", "azkey")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "usgovvirginia")
    tts = make_tts()
    assert isinstance(tts, AzureTts)
    assert tts.available() is True
    assert tts.label == "azure/usgovvirginia"


async def test_azure_tts_unconfigured_is_unavailable_and_raises():
    tts = AzureTts("", "", "tts.speech.microsoft.com", "en-US-JennyNeural")
    assert tts.available() is False
    agen = tts.synthesize_stream("hello", "v-1", "ignored")
    with pytest.raises(ValueError, match="not configured"):
        await agen.__anext__()
    # Empty text raises the same ValueError contract voices.synthesize_stream established.
    tts2 = AzureTts("k", "eastus", "tts.speech.microsoft.com", "en-US-JennyNeural")
    agen2 = tts2.synthesize_stream("   ", "v-1", "ignored")
    with pytest.raises(ValueError, match="empty text"):
        await agen2.__anext__()


def test_azure_voice_casting_map_and_default():
    tts = AzureTts("k", "eastus", "tts.speech.microsoft.com", "en-US-JennyNeural")
    tts._map = {"el-voice-abc": "en-US-AndrewNeural"}
    assert tts.map_voice("el-voice-abc") == "en-US-AndrewNeural"  # cast
    assert tts.map_voice("el-voice-unmapped") == "en-US-JennyNeural"  # default
    assert tts.map_voice("") == "en-US-JennyNeural"  # no assignment at all -> default
    tts._map = {"_default": "en-GB-SoniaNeural"}
    assert tts.map_voice("anything") == "en-GB-SoniaNeural"  # map-file default wins


class _FakeAzureResponse:
    status_code = 200
    request = None

    async def aiter_bytes(self):
        yield b"mp3-bytes-1"
        yield b"mp3-bytes-2"

    async def aread(self):
        return b""


class _FakeAzureStreamCM:
    def __init__(self, capture, response):
        self._capture = capture
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeAzureClient:
    def __init__(self, capture, response=None):
        self._capture = capture
        self._response = response or _FakeAzureResponse()

    def stream(self, method, url, *, content, headers):
        self._capture.update(method=method, url=url, content=content, headers=headers)
        return _FakeAzureStreamCM(self._capture, self._response)


async def test_azure_tts_builds_the_right_request(monkeypatch):
    captured = {}
    monkeypatch.setattr(tts_mod, "_azure_client", lambda: _FakeAzureClient(captured))
    tts = AzureTts("azkey", "eastus", "tts.speech.microsoft.com", "en-US-JennyNeural")
    tts._map = {"el-voice-abc": "en-US-AndrewNeural"}

    chunks = [
        c async for c in tts.synthesize_stream("Hi <there> & welcome", "el-voice-abc", "ignored")
    ]
    assert chunks == [b"mp3-bytes-1", b"mp3-bytes-2"]
    assert captured["url"] == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert captured["headers"]["Ocp-Apim-Subscription-Key"] == "azkey"
    assert captured["headers"]["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    ssml = captured["content"].decode()
    assert "en-US-AndrewNeural" in ssml  # the CAST voice, not the ElevenLabs id
    assert "Hi &lt;there&gt; &amp; welcome" in ssml  # XML-escaped text node
    # The Gov-cloud suffix swaps the endpoint host, nothing else.
    gov = AzureTts("azkey", "usgovvirginia", "tts.speech.azure.us", "en-US-JennyNeural")
    captured2 = {}
    monkeypatch.setattr(tts_mod, "_azure_client", lambda: _FakeAzureClient(captured2))
    _ = [c async for c in gov.synthesize_stream("hi", "", "ignored")]
    assert captured2["url"] == "https://usgovvirginia.tts.speech.azure.us/cognitiveservices/v1"


# --- /api/tts route contract — gating per provider, fallback semantics unchanged ------------------


async def test_tts_route_elevenlabs_gating_unchanged(monkeypatch):
    from portal import server

    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    # No key on the box (isolate from any dev keyfile/env leakage) -> 503 fallback, same reason as ever.
    monkeypatch.setattr(server, "_session_el_key", lambda: "")
    resp = await server._tts_response("hello", "v-1", None)
    assert resp.status_code == 503
    assert b"ElevenLabs not configured" in resp.body
    # Key present but no voice -> "no voice_id", unchanged.
    monkeypatch.setattr(server, "_session_el_key", lambda: "el-key")
    resp = await server._tts_response("hello", "", None)
    assert resp.status_code == 503
    assert b"no voice_id" in resp.body


async def test_tts_route_azure_unconfigured_falls_back(monkeypatch):
    from portal import server

    monkeypatch.setenv("TTS_PROVIDER", "azure")
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    monkeypatch.setattr(server, "_session_el_key", lambda: "")
    resp = await server._tts_response("hello", "v-1", None)
    assert resp.status_code == 503
    assert b"azure TTS not configured" in resp.body
