"""Helpers for coding-agent capture run construction."""

from __future__ import annotations

from typing import Any

from replaypack.agents import AgentAdapter
from replaypack.capture import (
    DEFAULT_REDACTION_POLICY,
    RedactionPolicy,
    capture_run,
)
from replaypack.core.models import Run


def build_agent_capture_run(
    *,
    adapter: AgentAdapter,
    agent: str,
    command: list[str],
    run_id: str,
    timestamp: str | None = None,
    redaction_policy: RedactionPolicy | None = None,
) -> Run:
    """Launch an agent adapter and normalize events into a ReplayKit run."""
    launch_result = adapter.launch(run_id=run_id, command=command)
    effective_policy = redaction_policy or DEFAULT_REDACTION_POLICY

    with capture_run(
        run_id=run_id,
        timestamp=timestamp,
        redaction_policy=effective_policy,
    ) as context:
        context.record_step(
            "agent.command",
            input_payload={"agent": agent, "command": command},
            output_payload={"returncode": launch_result.returncode},
            metadata={"agent": agent},
        )

        for event in launch_result.events:
            _record_agent_event(context=context, adapter=adapter, agent=agent, event=event)

        if launch_result.returncode != 0:
            context.record_step(
                "error.event",
                input_payload={"agent": agent, "command": command},
                output_payload={
                    "returncode": launch_result.returncode,
                    "stderr": launch_result.stderr,
                },
                metadata={"agent": agent},
            )

        context.record_step(
            "output.final",
            input_payload={"agent": agent},
            output_payload={
                "returncode": launch_result.returncode,
                "stdout": launch_result.stdout,
                "stderr": launch_result.stderr,
            },
            metadata={"agent": agent},
        )
        run = context.to_run()

    run.source = "agent.capture"
    run.agent = agent
    return run


def _record_agent_event(
    *,
    context: Any,
    adapter: AgentAdapter,
    agent: str,
    event: dict[str, Any],
) -> None:
    event_type = str(event.get("type", "")).strip().lower()
    metadata = {"agent": agent, "event_type": event_type}
    metadata.update(_event_metadata(event))

    if event_type == "model.request":
        context.record_step(
            "model.request",
            input_payload=event.get("input", {}),
            output_payload={"status": "sent"},
            metadata=metadata,
        )
    elif event_type == "model.response":
        context.record_step(
            "model.response",
            input_payload={"request_id": event.get("request_id")},
            output_payload=event.get("output", event),
            metadata=metadata,
        )
    elif event_type == "tool.request":
        context.record_step(
            "tool.request",
            input_payload=event.get("input", {}),
            output_payload={"status": "sent"},
            metadata=metadata,
        )
    elif event_type == "tool.response":
        context.record_step(
            "tool.response",
            input_payload={"tool": event.get("tool")},
            output_payload=adapter.normalize_tool_event(event.get("output", event)),
            metadata=metadata,
        )
    elif event_type == "error.event":
        context.record_step(
            "error.event",
            input_payload={"agent": agent},
            output_payload=event.get("output", event),
            metadata=metadata,
        )


def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return dict(metadata)

