"""Provider adapter contract for model capture integrations."""

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

    def capture_stream(self, *, chunks: Iterable[Any]) -> dict[str, Any]:
        """Normalize provider stream chunks and assembled text payload."""

    def capture_response(self, *, response: Any) -> dict[str, Any]:
        """Normalize non-stream provider response payload."""
