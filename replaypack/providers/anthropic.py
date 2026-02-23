"""Anthropic provider adapter."""

from __future__ import annotations

from typing import Any

from replaypack.capture import DEFAULT_REDACTION_POLICY, RedactionPolicy
from replaypack.providers.base import ProviderAdapter, default_provider_redact


class AnthropicProviderAdapter(ProviderAdapter):
    """Normalize Anthropic-style request/response payloads."""

    name = "anthropic"

    def normalize_request(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        url: str | None = None,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": model,
            "stream": stream,
            "url": url,
            "headers": headers or {},
            "payload": payload,
        }

    def normalize_stream_chunk(self, *, chunk: Any) -> dict[str, Any]:
        delta_text = ""
        if isinstance(chunk, dict):
            delta = chunk.get("delta")
            if isinstance(delta, dict):
                text = delta.get("text")
                if isinstance(text, str):
                    delta_text = text
        return {"provider": self.name, "chunk": chunk, "delta_text": delta_text}

    def normalize_response(self, *, response: Any) -> dict[str, Any]:
        return {"provider": self.name, "stream": False, "response": response}

    def redact(
        self,
        payload: Any,
        *,
        policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
    ) -> Any:
        return default_provider_redact(payload, policy=policy)

