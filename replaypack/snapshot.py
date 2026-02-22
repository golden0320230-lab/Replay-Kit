"""Snapshot workflow helpers for regression testing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from replaypack.artifact import read_artifact, write_artifact
from replaypack.diff import AssertionResult, assert_runs

SnapshotAction = Literal["update", "assert"]
SnapshotStatus = Literal["updated", "pass", "fail", "error"]


class SnapshotConfigError(ValueError):
    """Raised when snapshot workflow input is invalid."""


@dataclass(slots=True)
class SnapshotWorkflowResult:
    """Result model for snapshot update/assert workflows."""

    snapshot_name: str
    baseline_path: str
    candidate_path: str
    action: SnapshotAction
    status: SnapshotStatus
    strict: bool = False
    updated: bool = False
    assertion: AssertionResult | None = None
    message: str = ""

    @property
    def exit_code(self) -> int:
        return 0 if self.status in {"updated", "pass"} else 1

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "exit_code": self.exit_code,
            "action": self.action,
            "snapshot_name": self.snapshot_name,
            "baseline_path": self.baseline_path,
            "candidate_path": self.candidate_path,
            "strict": self.strict,
            "updated": self.updated,
            "message": self.message,
            "assertion": self.assertion.to_dict() if self.assertion is not None else None,
        }

        if self.assertion is not None:
            payload["first_divergence"] = self.assertion.to_dict()["first_divergence"]
        else:
            payload["first_divergence"] = None

        return payload


def resolve_snapshot_baseline_path(snapshot_name: str, snapshots_dir: str | Path) -> Path:
    """Resolve snapshot baseline path from snapshot name and snapshot directory."""
    normalized_name = snapshot_name.strip()
    if not normalized_name:
        raise SnapshotConfigError("snapshot_name must be non-empty")
    if "/" in normalized_name or "\\" in normalized_name:
        raise SnapshotConfigError("snapshot_name must not include path separators")

    filename = normalized_name if normalized_name.endswith(".rpk") else f"{normalized_name}.rpk"
    return Path(snapshots_dir) / filename


def update_snapshot_artifact(
    *,
    snapshot_name: str,
    candidate_path: str | Path,
    snapshots_dir: str | Path = "snapshots",
) -> SnapshotWorkflowResult:
    """Create or update snapshot baseline artifact from candidate artifact."""
    baseline_path = resolve_snapshot_baseline_path(snapshot_name, snapshots_dir)
    candidate_run = read_artifact(candidate_path)
    write_artifact(
        candidate_run,
        baseline_path,
        metadata={
            "snapshot_name": snapshot_name,
            "snapshot_mode": "update",
            "snapshot_source": str(candidate_path),
        },
    )

    return SnapshotWorkflowResult(
        snapshot_name=snapshot_name,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
        action="update",
        status="updated",
        strict=False,
        updated=True,
        message="snapshot baseline updated",
    )


def assert_snapshot_artifact(
    *,
    snapshot_name: str,
    candidate_path: str | Path,
    snapshots_dir: str | Path = "snapshots",
    strict: bool = False,
    max_changes_per_step: int = 32,
) -> SnapshotWorkflowResult:
    """Assert candidate artifact against snapshot baseline artifact."""
    baseline_path = resolve_snapshot_baseline_path(snapshot_name, snapshots_dir)
    if not baseline_path.exists():
        return SnapshotWorkflowResult(
            snapshot_name=snapshot_name,
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
            action="assert",
            status="error",
            strict=strict,
            updated=False,
            message="snapshot baseline missing; run with --update to create it",
        )

    baseline_run = read_artifact(baseline_path)
    candidate_run = read_artifact(candidate_path)
    result = assert_runs(
        baseline_run,
        candidate_run,
        strict=strict,
        max_changes_per_step=max(1, max_changes_per_step),
    )
    status: SnapshotStatus = "pass" if result.passed else "fail"

    return SnapshotWorkflowResult(
        snapshot_name=snapshot_name,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
        action="assert",
        status=status,
        strict=strict,
        updated=False,
        assertion=result,
        message="snapshot assertion passed" if result.passed else "snapshot assertion failed",
    )
