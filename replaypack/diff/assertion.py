"""Assertion helpers for CI-oriented regression checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from replaypack.core.canonical import canonicalize
from replaypack.core.models import Run
from replaypack.diff.engine import diff_runs
from replaypack.diff.models import RunDiffResult

StrictFailureKind = Literal["environment_mismatch", "runtime_mismatch", "metadata_drift"]


@dataclass(slots=True)
class StrictFailure:
    """Structured strict-mode failure detail."""

    kind: StrictFailureKind
    path: str
    left: Any
    right: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "left": self.left,
            "right": self.right,
        }


@dataclass(slots=True)
class AssertionResult:
    """Outcome of baseline vs candidate regression assertion."""

    diff: RunDiffResult
    passed: bool
    strict: bool = False
    strict_failures: list[StrictFailure] = field(default_factory=list)

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
            "strict": self.strict,
            "strict_failure_count": len(self.strict_failures),
            "strict_failures": [failure.to_dict() for failure in self.strict_failures],
            "first_divergence": (
                first_divergence.to_dict() if first_divergence is not None else None
            ),
        }


def assert_runs(
    baseline: Run,
    candidate: Run,
    *,
    strict: bool = False,
    max_changes_per_step: int = 32,
) -> AssertionResult:
    """Compare baseline vs candidate and return assertion outcome."""
    max_changes = max(1, max_changes_per_step)
    diff = diff_runs(
        baseline,
        candidate,
        stop_at_first_divergence=False,
        max_changes_per_step=max_changes,
    )

    strict_failures = (
        _collect_strict_failures(
            baseline,
            candidate,
            max_failures=max_changes,
        )
        if strict
        else []
    )

    return AssertionResult(
        diff=diff,
        passed=diff.identical and not strict_failures,
        strict=strict,
        strict_failures=strict_failures,
    )


def _collect_strict_failures(
    baseline: Run,
    candidate: Run,
    *,
    max_failures: int,
) -> list[StrictFailure]:
    failures: list[StrictFailure] = []

    left_env = canonicalize(baseline.environment_fingerprint, strip_volatile=False)
    right_env = canonicalize(candidate.environment_fingerprint, strip_volatile=False)
    if left_env != right_env:
        failures.append(
            StrictFailure(
                kind="environment_mismatch",
                path="/environment_fingerprint",
                left=left_env,
                right=right_env,
            )
        )
        if len(failures) >= max_failures:
            return failures

    left_runtime = canonicalize(baseline.runtime_versions, strip_volatile=False)
    right_runtime = canonicalize(candidate.runtime_versions, strip_volatile=False)
    if left_runtime != right_runtime:
        failures.append(
            StrictFailure(
                kind="runtime_mismatch",
                path="/runtime_versions",
                left=left_runtime,
                right=right_runtime,
            )
        )
        if len(failures) >= max_failures:
            return failures

    step_count = min(len(baseline.steps), len(candidate.steps))
    for idx in range(step_count):
        left_step = baseline.steps[idx]
        right_step = candidate.steps[idx]

        # Report strict metadata drift only when non-strict comparison would treat
        # the step as equivalent (same type + hash).
        if left_step.type != right_step.type:
            continue
        if (left_step.hash or "") != (right_step.hash or ""):
            continue

        left_metadata = canonicalize(left_step.metadata, strip_volatile=False)
        right_metadata = canonicalize(right_step.metadata, strip_volatile=False)
        if left_metadata == right_metadata:
            continue

        failures.append(
            StrictFailure(
                kind="metadata_drift",
                path=f"/steps/{idx + 1}/metadata",
                left=left_metadata,
                right=right_metadata,
            )
        )
        if len(failures) >= max_failures:
            return failures

    return failures
