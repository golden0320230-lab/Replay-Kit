from pathlib import Path

import replaykit

from replaypack.artifact import read_artifact, write_artifact
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


def test_strict_assertion_fails_on_environment_mismatch() -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))

    candidate.environment_fingerprint["os"] = "strict-env-drift"
    result = assert_runs(baseline, candidate, strict=True)

    assert result.passed is False
    assert result.diff.identical is True
    assert result.exit_code == 1
    assert any(failure.kind == "environment_mismatch" for failure in result.strict_failures)

    payload = result.to_dict()
    assert payload["status"] == "fail"
    assert payload["strict"] is True
    assert payload["strict_failure_count"] >= 1
    assert payload["first_divergence"] is None


def test_strict_assertion_catches_metadata_drift_hidden_from_non_strict() -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))

    # Volatile metadata changes are intentionally ignored by step hashing.
    candidate.steps[0].metadata["duration_ms"] = 999
    candidate.steps[0] = candidate.steps[0].with_hash()

    non_strict_result = assert_runs(baseline, candidate)
    strict_result = assert_runs(baseline, candidate, strict=True)

    assert non_strict_result.passed is True
    assert strict_result.passed is False
    assert any(failure.kind == "metadata_drift" for failure in strict_result.strict_failures)


def test_public_api_assert_run_supports_strict_mode(tmp_path: Path) -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate.runtime_versions["python"] = "9.9.9"

    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(baseline, baseline_path)
    write_artifact(candidate, candidate_path)

    non_strict_result = replaykit.assert_run(baseline_path, candidate_path)
    strict_result = replaykit.assert_run(baseline_path, candidate_path, strict=True)

    assert non_strict_result.passed is True
    assert strict_result.passed is False
    assert any(failure.kind == "runtime_mismatch" for failure in strict_result.strict_failures)
