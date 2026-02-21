"""Type definitions for ReplayKit core models."""

from typing import Literal

StepType = Literal[
    "prompt.render",
    "model.request",
    "model.response",
    "tool.request",
    "tool.response",
    "error.event",
    "output.final",
]

STEP_TYPES: tuple[str, ...] = (
    "prompt.render",
    "model.request",
    "model.response",
    "tool.request",
    "tool.response",
    "error.event",
    "output.final",
)
