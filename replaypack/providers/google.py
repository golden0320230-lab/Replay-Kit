"""Google Gemini provider adapter."""

from __future__ import annotations

from typing import Any

from replaypack.capture import DEFAULT_REDACTION_POLICY, RedactionPolicy
from replaypack.providers.base import ProviderAdapter, default_provider_redact


class GoogleProviderAdapter(ProviderAdapter):
    """Normalize Google Gemini-style request/response payloads."""

    name = "google"

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
            candidates = chunk.get("candidates")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, dict):
                    content = first.get("content")
                    if isinstance(content, dict):
                        parts = content.get("parts")
                        if isinstance(parts, list) and parts:
                            text = parts[0].get("text") if isinstance(parts[0], dict) else None
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

