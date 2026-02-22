"""Reference provider adapter for ReplayKit fake live-demo provider."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from replaypack.plugins.provider_api import ProviderAdapter


class FakeProviderAdapter(ProviderAdapter):
    """Reference adapter that normalizes fake provider request/stream/response."""

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

    def capture_stream(self, *, chunks: Iterable[Any]) -> dict[str, Any]:
        captured_chunks: list[Any] = []
        assembled: list[str] = []
        for chunk in chunks:
            captured_chunks.append(chunk)
            if isinstance(chunk, dict):
                choices = chunk.get("choices")
                if isinstance(choices, list) and choices:
                    first = choices[0]
                    if isinstance(first, dict):
                        delta = first.get("delta")
                        if isinstance(delta, dict):
                            content = delta.get("content")
                            if isinstance(content, str):
                                assembled.append(content)
        return {
            "provider": self.name,
            "stream": True,
            "chunks": captured_chunks,
            "assembled_text": "".join(assembled),
        }

    def capture_response(self, *, response: Any) -> dict[str, Any]:
        return {
            "provider": self.name,
            "stream": False,
            "response": response,
        }
