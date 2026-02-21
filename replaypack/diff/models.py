"""Data models for run diff and first-divergence reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DiffStatus = Literal["identical", "changed", "missing_left", "missing_right"]


@dataclass(slots=True)
class ValueChange:
    """A single value delta at a JSON pointer path."""

    path: str
    left: Any
    right: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "left": self.left,
            "right": self.right,
        }


@dataclass(slots=True)
class StepDiff:
    """Diff details for a single step position."""

    index: int
    status: DiffStatus
    left_step_id: str | None
    right_step_id: str | None
    left_type: str | None
    right_type: str | None
    context: dict[str, Any] = field(default_factory=dict)
    changes: list[ValueChange] = field(default_factory=list)
    truncated_changes: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "status": self.status,
            "left_step_id": self.left_step_id,
            "right_step_id": self.right_step_id,
            "left_type": self.left_type,
            "right_type": self.right_type,
            "context": self.context,
            "changes": [change.to_dict() for change in self.changes],
            "truncated_changes": self.truncated_changes,
        }


@dataclass(slots=True)
class RunDiffResult:
    """Structured diff for two runs."""

    left_run_id: str
    right_run_id: str
    total_left_steps: int
    total_right_steps: int
    step_diffs: list[StepDiff]

    @property
    def identical(self) -> bool:
        return all(step.status == "identical" for step in self.step_diffs)

    @property
    def first_divergence(self) -> StepDiff | None:
        for step in self.step_diffs:
            if step.status != "identical":
                return step
        return None

    def summary(self) -> dict[str, int]:
        counts = {
            "identical": 0,
            "changed": 0,
            "missing_left": 0,
            "missing_right": 0,
        }
        for step in self.step_diffs:
            counts[step.status] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "total_left_steps": self.total_left_steps,
            "total_right_steps": self.total_right_steps,
            "identical": self.identical,
            "summary": self.summary(),
            "first_divergence": (
                self.first_divergence.to_dict() if self.first_divergence is not None else None
            ),
            "step_diffs": [step.to_dict() for step in self.step_diffs],
        }
