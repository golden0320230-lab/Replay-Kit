"""Stable public API surface for ReplayKit.

This module is the supported import path for library users.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
import sys
import time
from typing import Any, Literal

from replaypack.artifact import (
    read_artifact,
    redact_run_for_bundle,
    write_artifact,
    write_bundle_artifact,
)
from replaypack.capture import RedactionPolicy, build_demo_run
from replaypack.capture import (
    CaptureContext,
    InterceptionPolicy,
    capture_run,
    intercept_httpx,
    intercept_requests,
    tool,
)
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
CaptureInterceptor = Literal["httpx", "requests"]
RecordResult = dict[str, Any]


@dataclass(slots=True)
class _RecordCaptureScope:
    """Context manager that captures a user-owned code block and writes artifact on exit."""

    path: str | Path
    intercept: tuple[CaptureInterceptor, ...]
    redaction_policy: RedactionPolicy | None
    run_id: str | None
    timestamp: str | None
    _capture_scope: Any = field(default=None, init=False, repr=False)
    _capture_context: CaptureContext | None = field(default=None, init=False, repr=False)
    _intercept_stack: ExitStack | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> CaptureContext:
        resolved_run_id = self.run_id or f"run-record-context-{int(time.time() * 1000)}"
        self._capture_scope = capture_run(
            run_id=resolved_run_id,
            timestamp=self.timestamp,
            policy=InterceptionPolicy(capture_http_bodies=True),
            redaction_policy=self.redaction_policy,
        )
        self._capture_context = self._capture_scope.__enter__()
        self._intercept_stack = ExitStack()
        try:
            if "requests" in self.intercept:
                self._intercept_stack.enter_context(
                    intercept_requests(context=self._capture_context)
                )
            if "httpx" in self.intercept:
                self._intercept_stack.enter_context(intercept_httpx(context=self._capture_context))
        except Exception:
            self._intercept_stack.close()
            self._capture_scope.__exit__(*sys.exc_info())
            raise
        return self._capture_context

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if (
            self._capture_scope is None
            or self._capture_context is None
            or self._intercept_stack is None
        ):
            return False

        self._intercept_stack.close()
        suppress = self._capture_scope.__exit__(exc_type, exc, tb)
        run = self._capture_context.to_run()
        write_artifact(
            run,
            self.path,
            metadata={
                "api": "replaykit.record",
                "mode": "capture-context",
                "intercept": list(self.intercept),
            },
        )
        return suppress


def _normalize_interceptors(
    intercept: tuple[CaptureInterceptor, ...] | list[CaptureInterceptor],
) -> tuple[CaptureInterceptor, ...]:
    allowed = {"httpx", "requests"}
    normalized: list[CaptureInterceptor] = []
    for name in intercept:
        normalized_name = str(name).strip()
        if normalized_name not in allowed:
            raise ValueError(
                f"Unsupported intercept option: {normalized_name}. "
                "Supported values: httpx, requests."
            )
        if normalized_name == "httpx":
            normalized.append("httpx")
        else:
            normalized.append("requests")
    if not normalized:
        return ("httpx", "requests")
    return tuple(dict.fromkeys(normalized))


# NOTE: This function currently records the deterministic demo workflow.
def record(
    path: str | Path,
    *,
    mode: ReplayMode = "stub",
    redaction: bool = True,
    redaction_policy: RedactionPolicy | None = None,
    intercept: tuple[CaptureInterceptor, ...] | list[CaptureInterceptor] | None = None,
    run_id: str | None = None,
    timestamp: str | None = None,
) -> RecordResult | _RecordCaptureScope:
    """Record a run artifact to disk.

    Args:
        path: Output artifact path.
        mode: Recording mode. Only ``"stub"`` is supported.
        redaction: Whether redaction is enabled. Only ``True`` is supported in the
            current record flow.
        intercept: When provided, return a context manager that captures a user code
            block with selected interceptors.
        run_id: Optional run id for context-manager capture mode.
        timestamp: Optional timestamp override for context-manager capture mode.

    Returns:
        Artifact envelope dictionary for one-shot demo mode, or a context manager for
        integration mode.

    Raises:
        ValueError: If unsupported mode/redaction arguments are provided.
    """
    if mode != "stub":
        raise ValueError(f"Unsupported record mode: {mode}")
    if not redaction:
        raise ValueError("record(..., redaction=False) is not supported yet")
    if intercept is not None:
        return _RecordCaptureScope(
            path=path,
            intercept=_normalize_interceptors(intercept),
            redaction_policy=redaction_policy,
            run_id=run_id,
            timestamp=timestamp,
        )

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
    "CaptureInterceptor",
    "AssertionResult",
    "RunDiffResult",
    "SnapshotWorkflowResult",
    "tool",
    "record",
    "replay",
    "diff",
    "assert_run",
    "bundle",
    "snapshot_assert",
]
