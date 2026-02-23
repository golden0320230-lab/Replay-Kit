"""Passive coding-agent event normalization for listener mode."""

from __future__ import annotations

from typing import Any


_SUPPORTED_AGENTS = {"codex", "claude-code"}


def detect_agent(path: str) -> str | None:
    normalized = path.strip().rstrip("/")
    if normalized == "/agent/codex/events":
        return "codex"
    if normalized == "/agent/claude-code/events":
        return "claude-code"
    return None


def normalize_agent_events(
    *,
    agent: str,
    payload: Any,
) -> tuple[list[dict[str, Any]], int]:
    if agent not in _SUPPORTED_AGENTS:
        raise ValueError(f"unsupported agent: {agent}")

    raw_events: list[Any]
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        raw_events = list(payload["events"])
    elif isinstance(payload, list):
        raw_events = list(payload)
    elif isinstance(payload, dict):
        raw_events = [payload]
    else:
        return [], 1

    normalized: list[dict[str, Any]] = []
    dropped = 0
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            dropped += 1
            continue

        event_type = str(raw_event.get("type", "")).strip().lower()
        if not event_type:
            dropped += 1
            continue

        metadata = {"agent": agent, "event_type": event_type}
        extra_metadata = raw_event.get("metadata")
        if isinstance(extra_metadata, dict):
            metadata.update(extra_metadata)

        request_id = raw_event.get("request_id")
        normalized_event: dict[str, Any]
        if event_type == "model.request":
            normalized_event = {
                "step_type": "model.request",
                "input": raw_event.get("input", {}),
                "output": {"status": "captured"},
                "metadata": metadata,
                "request_id": request_id,
            }
        elif event_type == "model.response":
            normalized_event = {
                "step_type": "model.response",
                "input": {"request_id": request_id},
                "output": raw_event.get("output", raw_event),
                "metadata": metadata,
                "request_id": request_id,
            }
        elif event_type == "tool.request":
            normalized_event = {
                "step_type": "tool.request",
                "input": raw_event.get("input", {}),
                "output": {"status": "captured"},
                "metadata": metadata,
                "request_id": request_id,
            }
        elif event_type == "tool.response":
            normalized_event = {
                "step_type": "tool.response",
                "input": {"tool": raw_event.get("tool")},
                "output": {"agent": agent, "event": raw_event.get("output", raw_event)},
                "metadata": metadata,
                "request_id": request_id,
            }
        elif event_type == "error.event":
            normalized_event = {
                "step_type": "error.event",
                "input": {"agent": agent},
                "output": raw_event.get("output", raw_event),
                "metadata": metadata,
                "request_id": request_id,
            }
        else:
            dropped += 1
            continue

        normalized.append(normalized_event)

    return normalized, dropped
