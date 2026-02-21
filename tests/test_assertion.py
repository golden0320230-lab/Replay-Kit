from pathlib import Path

from replaypack.artifact import read_artifact
from replaypack.diff import assert_runs


def test_assertion_passes_for_identical_runs() -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))

    result = assert_runs(baseline, candidate)

    assert result.passed is True
    assert result.exit_code == 0
    payload = result.to_dict()
    assert payload["status"] == "pass"
    assert payload["first_divergence"] is None


def test_assertion_fails_for_diverged_runs() -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m4_diverged_from_m2.rpk"))

    result = assert_runs(baseline, candidate)

    assert result.passed is False
    assert result.exit_code == 1
    payload = result.to_dict()
    assert payload["status"] == "fail"
    assert payload["first_divergence"]["index"] == 3
