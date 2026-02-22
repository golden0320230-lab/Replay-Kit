"""Canonical provider adapter contract."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol


class ProviderAdapter(Protocol):
    """Protocol for provider-specific capture normalization."""

    name: str

    def capture_request(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        stream: bool,
    ) -> dict[str, Any]:
        """Normalize provider request payload before capture."""

    def capture_stream_chunk(self, *, chunk: Any) -> dict[str, Any]:
        """Normalize one stream chunk from a provider response stream."""

    def capture_response(self, *, response: Any) -> dict[str, Any]:
        """Normalize non-stream provider response payload."""


def assemble_stream_capture(
    adapter: ProviderAdapter,
    *,
    chunks: Iterable[Any],
) -> dict[str, Any]:
    """Capture stream chunks and deterministically assemble response text."""
    captured_chunks: list[dict[str, Any]] = []
    assembled_parts: list[str] = []

    for chunk in chunks:
        normalized_chunk = adapter.capture_stream_chunk(chunk=chunk)
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
