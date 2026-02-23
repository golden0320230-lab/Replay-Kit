"""Canonical provider adapter contract."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from replaypack.capture import DEFAULT_REDACTION_POLICY, RedactionPolicy, redact_payload


class ProviderAdapter(Protocol):
    """Protocol for provider-specific capture normalization."""

    name: str

    def normalize_request(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        url: str | None = None,
        stream: bool,
    ) -> dict[str, Any]:
        """Normalize provider request payload before capture."""

    def normalize_stream_chunk(self, *, chunk: Any) -> dict[str, Any]:
        """Normalize one stream chunk from a provider response stream."""

    def normalize_response(self, *, response: Any) -> dict[str, Any]:
        """Normalize non-stream provider response payload."""

    def redact(
        self,
        payload: Any,
        *,
        policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
    ) -> Any:
        """Apply provider-level redaction before artifact persistence."""


def assemble_stream_capture(
    adapter: ProviderAdapter,
    *,
    chunks: Iterable[Any],
) -> dict[str, Any]:
    """Capture stream chunks and deterministically assemble response text."""
    captured_chunks: list[dict[str, Any]] = []
    assembled_parts: list[str] = []

    for chunk in chunks:
        normalized_chunk = adapter.normalize_stream_chunk(chunk=chunk)
        captured_chunks.append(normalized_chunk)

        delta_text = normalized_chunk.get("delta_text")
        if isinstance(delta_text, str):
            assembled_parts.append(delta_text)

    return {
        "provider": adapter.name,
        "stream": True,
        "chunks": captured_chunks,
        "assembled_text": "".join(assembled_parts),
    }


def default_provider_redact(
    payload: Any,
    *,
    policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
) -> Any:
    """Default provider redaction implementation."""
    return redact_payload(payload, policy=policy)
