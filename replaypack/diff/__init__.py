"""Diff subsystem for ReplayKit."""

from replaypack.diff.assertion import AssertionResult, assert_runs
from replaypack.diff.engine import diff_runs
from replaypack.diff.formatting import render_diff_summary, render_first_divergence
from replaypack.diff.models import DiffStatus, RunDiffResult, StepDiff, ValueChange

__all__ = [
    "DiffStatus",
    "ValueChange",
    "StepDiff",
    "RunDiffResult",
    "diff_runs",
    "AssertionResult",
    "assert_runs",
    "render_diff_summary",
    "render_first_divergence",
]
