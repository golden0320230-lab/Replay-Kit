"""Agent adapter contracts and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class AgentLaunchResult:
    """Normalized result emitted by an agent adapter launch call."""

    run_id: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    events: list[dict[str, Any]]


class AgentAdapter(Protocol):
    """Protocol for coding-agent capture adapters."""

    name: str

    def launch(self, *, run_id: str, command: list[str]) -> AgentLaunchResult:
        """Launch a target command and collect raw events."""

    def normalize_tool_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalize tool event shape before capture persistence."""

