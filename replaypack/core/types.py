"""Type definitions for ReplayKit core models."""

from typing import Literal

StepType = Literal[
    "agent.command",
    "prompt.render",
    "model.request",
    "model.response",
    "tool.request",
    "tool.response",
    "error.event",
    "output.final",
]

STEP_TYPES: tuple[str, ...] = (
    "agent.command",
    "prompt.render",
    "model.request",
    "model.response",
    "tool.request",
    "tool.response",
    "error.event",
    "output.final",
)
