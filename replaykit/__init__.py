"""Stable public API surface for ReplayKit.

This module is the supported import path for library users.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from replaypack.artifact import (
    read_artifact,
    redact_run_for_bundle,
    write_artifact,
    write_bundle_artifact,
)
from replaypack.capture import RedactionPolicy, build_demo_run
from replaypack.diff import assert_runs, diff_runs
from replaypack.diff.assertion import AssertionResult
from replaypack.diff.models import RunDiffResult
from replaypack.replay import (
    HybridReplayPolicy,
    ReplayConfig,
    write_replay_hybrid_artifact,
    write_replay_stub_artifact,
)
from replaypack.snapshot import (
    SnapshotWorkflowResult,
    assert_snapshot_artifact,
    update_snapshot_artifact,
)

__version__ = "0.1.0"

ReplayMode = Literal["stub", "hybrid"]


# NOTE: This function currently records the deterministic demo workflow.
def record(
    path: str | Path,
    *,
    mode: ReplayMode = "stub",
    redaction: bool = True,
    redaction_policy: RedactionPolicy | None = None,
) -> dict[str, Any]:
    """Record a run artifact to disk.

    Args:
        path: Output artifact path.
        mode: Recording mode. Only ``"stub"`` is supported.
        redaction: Whether redaction is enabled. Only ``True`` is supported in the
            current record flow.

    Returns:
        Artifact envelope as a dictionary.

    Raises:
        ValueError: If unsupported mode/redaction arguments are provided.
    """
    if mode != "stub":
        raise ValueError(f"Unsupported record mode: {mode}")
    if not redaction:
        raise ValueError("record(..., redaction=False) is not supported yet")

    run = build_demo_run(redaction_policy=redaction_policy)
    return write_artifact(run, path, metadata={"api": "replaykit.record", "mode": mode})


def replay(
    path: str | Path,
    *,
    out: str | Path,
    mode: ReplayMode = "stub",
    seed: int = 0,
    fixed_clock: str = "2026-01-01T00:00:00Z",
    rerun_from: str | Path | None = None,
    rerun_step_types: tuple[str, ...] = (),
    rerun_step_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Replay an artifact in deterministic stub or hybrid mode.

    Args:
        path: Source artifact path.
        out: Output replay artifact path.
        mode: Replay mode (``"stub"`` or ``"hybrid"``).
        seed: Deterministic replay seed.
        fixed_clock: Fixed replay timestamp in ISO-8601 with timezone.
        rerun_from: Required in hybrid mode. Artifact used as rerun source.
        rerun_step_types: Hybrid mode step-type selectors to rerun.
        rerun_step_ids: Hybrid mode step-id selectors to rerun.

    Returns:
        Replay artifact envelope.

    Raises:
        ValueError: If unsupported replay mode is provided.
    """
    if mode not in {"stub", "hybrid"}:
        raise ValueError(f"Unsupported replay mode: {mode}")

    source_run = read_artifact(path)
    config = ReplayConfig(seed=seed, fixed_clock=fixed_clock)
    if mode == "stub":
        return write_replay_stub_artifact(source_run, str(out), config=config)

    if rerun_from is None:
        raise ValueError("replay(..., mode='hybrid') requires rerun_from")
    policy = HybridReplayPolicy(
        rerun_step_types=tuple(rerun_step_types),
        rerun_step_ids=tuple(rerun_step_ids),
    )
    rerun_run = read_artifact(rerun_from)
    return write_replay_hybrid_artifact(
        source_run,
        rerun_run,
        str(out),
        config=config,
        policy=policy,
    )


def diff(
    left: str | Path,
    right: str | Path,
    *,
    first_only: bool = False,
    max_changes_per_step: int = 32,
    redaction_policy: RedactionPolicy | None = None,
) -> RunDiffResult:
    """Diff two artifacts and return structured comparison data.

    Args:
        left: Left artifact path.
        right: Right artifact path.
        first_only: Stop scanning when first divergence is found.
        max_changes_per_step: Maximum field-level changes collected per step.

    Returns:
        Structured run diff result.
    """
    left_run = read_artifact(left)
    right_run = read_artifact(right)
    if redaction_policy is not None:
        left_run = redact_run_for_bundle(left_run, policy=redaction_policy)
        right_run = redact_run_for_bundle(right_run, policy=redaction_policy)
    return diff_runs(
        left_run,
        right_run,
        stop_at_first_divergence=first_only,
        max_changes_per_step=max_changes_per_step,
    )


def assert_run(
    baseline: str | Path,
    candidate: str | Path,
    *,
    strict: bool = False,
    max_changes_per_step: int = 32,
) -> AssertionResult:
    """Assert candidate artifact behavior against baseline.

    Args:
        baseline: Baseline artifact path.
        candidate: Candidate artifact path.
        strict: Enable strict drift checks for environment/runtime metadata and
            per-step metadata drift.
        max_changes_per_step: Maximum field-level changes collected per step.

    Returns:
        Assertion result object with pass/fail and diff payload.
    """
    baseline_run = read_artifact(baseline)
    candidate_run = read_artifact(candidate)
    return assert_runs(
        baseline_run,
        candidate_run,
        strict=strict,
        max_changes_per_step=max_changes_per_step,
    )


def bundle(
    path: str | Path,
    *,
    out: str | Path,
    redaction_profile: str = "default",
    redaction_policy: RedactionPolicy | None = None,
) -> dict[str, Any]:
    """Export a bundle artifact using the requested redaction profile.

    Args:
        path: Source artifact path.
        out: Bundle output path.
        redaction_profile: Redaction profile name.

    Returns:
        Bundle artifact envelope.
    """
    return write_bundle_artifact(
        path,
        out,
        redaction_profile=redaction_profile,
        redaction_policy=redaction_policy,
        redaction_profile_label="custom" if redaction_policy is not None else None,
    )


def snapshot_assert(
    name: str,
    candidate: str | Path,
    *,
    snapshots_dir: str | Path = "snapshots",
    update: bool = False,
    strict: bool = False,
    max_changes_per_step: int = 32,
) -> SnapshotWorkflowResult:
    """Run snapshot update/assert workflow for a candidate artifact.

    Args:
        name: Snapshot baseline name (stored as `<name>.rpk`).
        candidate: Candidate artifact path.
        snapshots_dir: Baseline snapshot directory.
        update: If true, create/update baseline from candidate.
        strict: Strict drift gating when asserting.
        max_changes_per_step: Max field-level changes in assertion payload.

    Returns:
        Snapshot workflow result model.
    """
    if update:
        return update_snapshot_artifact(
            snapshot_name=name,
            candidate_path=candidate,
            snapshots_dir=snapshots_dir,
        )
    return assert_snapshot_artifact(
        snapshot_name=name,
        candidate_path=candidate,
        snapshots_dir=snapshots_dir,
        strict=strict,
        max_changes_per_step=max_changes_per_step,
    )


__all__ = [
    "__version__",
    "ReplayMode",
    "AssertionResult",
    "RunDiffResult",
    "SnapshotWorkflowResult",
    "record",
    "replay",
    "diff",
    "assert_run",
    "bundle",
    "snapshot_assert",
]
