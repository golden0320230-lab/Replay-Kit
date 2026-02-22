"""Reference provider adapter for local deterministic testing."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from replaypack.providers.base import ProviderAdapter, assemble_stream_capture


class FakeProviderAdapter(ProviderAdapter):
    """Reference adapter for fake provider request/stream/response capture."""

    name = "fake"

    def capture_request(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": model,
            "stream": stream,
            "payload": payload,
        }

    def capture_stream_chunk(self, *, chunk: Any) -> dict[str, Any]:
        delta_text = ""
        if isinstance(chunk, dict):
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    delta = first.get("delta")
                    if isinstance(delta, dict):
                        content = delta.get("content")
                        if isinstance(content, str):
                            delta_text = content

        return {
            "provider": self.name,
            "chunk": chunk,
            "delta_text": delta_text,
        }

    def capture_response(self, *, response: Any) -> dict[str, Any]:
        return {
            "provider": self.name,
            "stream": False,
            "response": response,
        }

    def capture_stream(self, *, chunks: Iterable[Any]) -> dict[str, Any]:
        """Convenience helper mirroring legacy adapter stream API."""
        return assemble_stream_capture(self, chunks=chunks)
