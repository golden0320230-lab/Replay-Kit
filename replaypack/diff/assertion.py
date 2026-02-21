"""Assertion helpers for CI-oriented regression checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from replaypack.core.models import Run
from replaypack.diff.engine import diff_runs
from replaypack.diff.models import RunDiffResult


@dataclass(slots=True)
class AssertionResult:
    """Outcome of baseline vs candidate regression assertion."""

    diff: RunDiffResult
    passed: bool

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1

    def to_dict(self) -> dict[str, Any]:
        first_divergence = self.diff.first_divergence
        return {
            "status": "pass" if self.passed else "fail",
            "exit_code": self.exit_code,
            "baseline_run_id": self.diff.left_run_id,
            "candidate_run_id": self.diff.right_run_id,
            "total_baseline_steps": self.diff.total_left_steps,
            "total_candidate_steps": self.diff.total_right_steps,
            "summary": self.diff.summary(),
            "first_divergence": (
                first_divergence.to_dict() if first_divergence is not None else None
            ),
        }


def assert_runs(
    baseline: Run,
    candidate: Run,
    *,
    max_changes_per_step: int = 32,
) -> AssertionResult:
    """Compare baseline vs candidate and return assertion outcome."""
    diff = diff_runs(
        baseline,
        candidate,
        stop_at_first_divergence=False,
        max_changes_per_step=max_changes_per_step,
    )
    return AssertionResult(diff=diff, passed=diff.identical)
