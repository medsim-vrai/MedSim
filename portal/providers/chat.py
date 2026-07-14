"""Chat-completion providers — one interface, three transports (V8 gate 1).

``ChatProvider.complete(system, messages, max_tokens) -> str`` and ``.stream(...)`` (a sync generator of
text deltas) take the SAME prompt ``portal.runtime`` builds for every vendor. ``messages`` is the
Anthropic/OpenAI-shared shape: ``[{"role": "user"|"assistant", "content": "..."}]`` with ``system``
carried separately.

The default (Anthropic) provider is keyed PER-SESSION — V8's existing trust model has the operator paste
an Anthropic key into the vault at session start (``session.api_key``), not a single deploy-wide key —
so ``make_chat`` takes that key and threads it straight to ``AnthropicChat`` when no other provider is
selected, reproducing today's ``Anthropic(api_key=session.api_key)`` call exactly. A selected alternate
provider (Azure OpenAI, Bedrock) is org-wide config (env), matching how a real Gov/DoD deployment is
actually provisioned — not a per-instructor-typed key.

Only Anthropic implements true streaming here (it is the default, and the avatar's first-sentence-early
optimization depends on it). Azure OpenAI and Bedrock implement ``stream()`` as a single-chunk fallback
via ``complete()`` — correct behavior, just without that latency optimization, exactly the trade-off V9's
gate 1 made for its non-default providers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Protocol


class ChatProvider(Protocol):
    name: str
    label: str  # engine identifier (model/deployment id)

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str: ...
    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Iterator[str]: ...


class _CompleteThenYield:
    """Mixin: a provider with no native streaming yields its whole ``complete()`` result as one chunk."""

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Iterator[str]:
        yield self.complete(system=system, messages=messages, max_tokens=max_tokens)


class AnthropicChat:
    """Claude via the Anthropic Messages API — today's production path, keyed per-session."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self._key = api_key or ""
        self._model = model

    @property
    def label(self) -> str:
        return self._model

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._key)
        response = client.messages.create(
            model=self._model, max_tokens=max_tokens, system=system, messages=messages
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Iterator[str]:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._key)
        with client.messages.stream(
            model=self._model, max_tokens=max_tokens, system=system, messages=messages
        ) as stream:
            yield from stream.text_stream


class AzureOpenAIChat(_CompleteThenYield):
    """GPT via Azure OpenAI — the procurable Azure Government path for sites where Claude is not
    procurable (FASCSA). Endpoint like ``https://<resource>.openai.azure.com`` (``...azure.us`` in Gov)."""

    name = "azure_openai"

    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str) -> None:
        self._endpoint = (endpoint or "").rstrip("/")
        self._key = api_key or ""
        self._deployment = deployment or ""
        self._api_version = api_version or "2024-10-21"

    @property
    def label(self) -> str:
        return f"azure/{self._deployment}"

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        import httpx

        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}"
            f"/chat/completions?api-version={self._api_version}"
        )
        resp = httpx.post(
            url,
            headers={"api-key": self._key, "content-type": "application/json"},
            json={"messages": msgs, "max_tokens": max_tokens},
            timeout=45,
        )
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()


class BedrockChat(_CompleteThenYield):
    """Claude (or a non-Anthropic model) via AWS Bedrock. Lazy boto3 import — if it isn't installed the
    provider simply cannot be constructed with real credentials; callers see the ImportError at
    complete()-time, same failure shape as a bad Anthropic key today (caught + friendly-messaged)."""

    name = "bedrock"

    def __init__(self, model_id: str, region: str) -> None:
        self._model_id = model_id or ""
        self._region = region or ""

    @property
    def label(self) -> str:
        return f"bedrock/{self._model_id}"

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=self._region)
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        resp = client.invoke_model(modelId=self._model_id, body=json.dumps(body))
        data = json.loads(resp["body"].read())
        return "".join(b.get("text", "") for b in data.get("content", [])).strip()


def make_chat(*, session_api_key: str, model: str) -> ChatProvider:
    """Select the chat provider from LLM_PROVIDER (default anthropic -> today's stack, inert).

    ``session_api_key`` is the operator-supplied key from the running session — used ONLY by the
    Anthropic provider, preserving V8's existing per-session-key trust model exactly. Azure OpenAI and
    Bedrock read their own env-configured credentials (an org-wide deployment concern, not a per-session
    one), matching the pattern in V9's ``app/providers/chat.py``. ``model`` is ``runtime.MODEL`` — passed
    in rather than duplicated here, so there is one source of truth for the default Anthropic model id.
    """
    import os

    provider = (os.environ.get("LLM_PROVIDER", "") or "anthropic").lower()
    if provider == "azure_openai":
        return AzureOpenAIChat(
            os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            os.environ.get("AZURE_OPENAI_KEY", ""),
            os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
            os.environ.get("AZURE_OPENAI_API_VERSION", "") or "2024-10-21",
        )
    if provider == "bedrock":
        return BedrockChat(
            os.environ.get("BEDROCK_MODEL_ID", "") or "anthropic.claude-haiku-4-5-20251001-v1:0",
            os.environ.get("BEDROCK_REGION", "") or "us-gov-west-1",
        )
    return AnthropicChat(session_api_key, model)
