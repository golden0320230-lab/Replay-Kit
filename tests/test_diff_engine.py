from pathlib import Path

from replaypack.artifact import read_artifact
from replaypack.diff import diff_runs


def test_diff_identical_runs_have_no_divergence() -> None:
    left = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    right = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))

    result = diff_runs(left, right)

    assert result.identical is True
    assert result.first_divergence is None
    assert result.summary()["identical"] == len(left.steps)


def test_diff_finds_first_divergence_and_field_changes() -> None:
    left = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    right = read_artifact(Path("examples/runs/m4_diverged_from_m2.rpk"))

    result = diff_runs(left, right)

    first = result.first_divergence
    assert first is not None
    assert first.index == 3
    assert first.status == "changed"
    assert first.context["tool"] == {"left": "search", "right": "search-v2"}

    changed_paths = {change.path for change in first.changes}
    assert "/input/args/0" in changed_paths
    assert "/metadata/tool" in changed_paths


def test_diff_stop_at_first_divergence_limits_output_steps() -> None:
    left = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    right = read_artifact(Path("examples/runs/m4_diverged_from_m2.rpk"))

    result = diff_runs(left, right, stop_at_first_divergence=True)

    assert len(result.step_diffs) == 3
    assert result.first_divergence is not None
    assert result.first_divergence.index == 3


def test_diff_marks_missing_right_step() -> None:
    left = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    right = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    right.steps = right.steps[:-1]

    result = diff_runs(left, right)
    first = result.first_divergence

    assert first is not None
    assert first.index == 6
    assert first.status == "missing_right"
