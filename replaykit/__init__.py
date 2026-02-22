"""Stable public API surface for ReplayKit.

This module is the supported import path for library users.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from replaypack.artifact import read_artifact, write_artifact, write_bundle_artifact
from replaypack.capture import build_demo_run
from replaypack.diff import assert_runs, diff_runs
from replaypack.diff.assertion import AssertionResult
from replaypack.diff.models import RunDiffResult
from replaypack.replay import ReplayConfig, write_replay_stub_artifact

__version__ = "0.1.0"

ReplayMode = Literal["stub"]


# NOTE: This function currently records the deterministic demo workflow.
def record(
    path: str | Path,
    *,
    mode: ReplayMode = "stub",
    redaction: bool = True,
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

    run = build_demo_run()
    return write_artifact(run, path, metadata={"api": "replaykit.record", "mode": mode})


def replay(
    path: str | Path,
    *,
    out: str | Path,
    mode: ReplayMode = "stub",
    seed: int = 0,
    fixed_clock: str = "2026-01-01T00:00:00Z",
) -> dict[str, Any]:
    """Replay an artifact in deterministic stub mode.

    Args:
        path: Source artifact path.
        out: Output replay artifact path.
        mode: Replay mode. Only ``"stub"`` is supported.
        seed: Deterministic replay seed.
        fixed_clock: Fixed replay timestamp in ISO-8601 with timezone.

    Returns:
        Replay artifact envelope.

    Raises:
        ValueError: If unsupported replay mode is provided.
    """
    if mode != "stub":
        raise ValueError(f"Unsupported replay mode: {mode}")

    source_run = read_artifact(path)
    config = ReplayConfig(seed=seed, fixed_clock=fixed_clock)
    return write_replay_stub_artifact(source_run, str(out), config=config)


def diff(
    left: str | Path,
    right: str | Path,
    *,
    first_only: bool = False,
    max_changes_per_step: int = 32,
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
        strict: Reserved for strict-mode semantics (not yet implemented).
        max_changes_per_step: Maximum field-level changes collected per step.

    Returns:
        Assertion result object with pass/fail and diff payload.

    Raises:
        NotImplementedError: If strict mode is requested.
    """
    if strict:
        raise NotImplementedError("strict mode is not implemented yet")

    baseline_run = read_artifact(baseline)
    candidate_run = read_artifact(candidate)
    return assert_runs(
        baseline_run,
        candidate_run,
        max_changes_per_step=max_changes_per_step,
    )


def bundle(
    path: str | Path,
    *,
    out: str | Path,
    redaction_profile: str = "default",
) -> dict[str, Any]:
    """Export a bundle artifact using the requested redaction profile.

    Args:
        path: Source artifact path.
        out: Bundle output path.
        redaction_profile: Redaction profile name.

    Returns:
        Bundle artifact envelope.
    """
    return write_bundle_artifact(path, out, redaction_profile=redaction_profile)


__all__ = [
    "__version__",
    "ReplayMode",
    "AssertionResult",
    "RunDiffResult",
    "record",
    "replay",
    "diff",
    "assert_run",
    "bundle",
]
