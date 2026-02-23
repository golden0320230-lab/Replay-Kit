"""Codex agent adapter."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from replaypack.agents.base import AgentAdapter, AgentLaunchResult


class CodexAgentAdapter(AgentAdapter):
    """Adapter for codex-style command execution and event parsing."""

    name = "codex"

    def launch(self, *, run_id: str, command: list[str]) -> AgentLaunchResult:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        return AgentLaunchResult(
            run_id=run_id,
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            events=_parse_json_lines(completed.stdout),
        )

    def normalize_tool_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {"agent": self.name, "event": event}


def _parse_json_lines(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events

