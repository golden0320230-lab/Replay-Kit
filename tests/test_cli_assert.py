import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact, write_artifact
from replaypack.cli.app import app
from replaypack.core.models import Run, Step


def _guardrail_run(run_id: str, request_id: str, *, uses_random: bool = True) -> Run:
    runtime_versions = {
        "python": "3.12.0",
        "replaykit": "0.1.0",
    }
    if uses_random:
        runtime_versions["uses_random"] = "true"

    return Run(
        id=run_id,
        timestamp="2026-02-22T18:30:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions=runtime_versions,
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": request_id},
                output={"content": "hi", "timestamp": "2026-02-22T18:30:00Z"},
                metadata={"provider": "openai"},
            ),
        ],
    )


def _timed_run(run_id: str, duration_ms: float) -> Run:
    return Run(
        id=run_id,
        timestamp="2026-02-22T18:30:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={
            "python": "3.12.0",
            "replaykit": "0.1.0",
        },
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"duration_ms": duration_ms},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "req-001"},
                output={"content": "hi"},
                metadata={"duration_ms": duration_ms},
            ),
        ],
    )


def test_cli_assert_passes_with_identical_artifacts() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
        ],
    )

    assert result.exit_code == 0
    assert "assert passed" in result.stdout


def test_cli_assert_fails_on_divergence() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m4_diverged_from_m2.rpk",
        ],
    )

    assert result.exit_code == 1
    assert "assert failed" in result.stdout
    assert "first divergence: step 3" in result.stdout


def test_cli_assert_json_output_pass() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["exit_code"] == 0


def test_cli_assert_json_output_fail() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m4_diverged_from_m2.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["first_divergence"]["index"] == 3


def test_cli_assert_strict_passes_with_identical_artifacts() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
            "--strict",
        ],
    )

    assert result.exit_code == 0
    assert "assert passed (strict)" in result.stdout


def test_cli_assert_strict_json_fails_on_runtime_mismatch(tmp_path: Path) -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate.runtime_versions["python"] = "strict-runtime-drift"

    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(baseline, baseline_path)
    write_artifact(candidate, candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--strict",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["strict"] is True
    assert payload["first_divergence"] is None
    assert payload["summary"]["changed"] == 0
    assert any(
        failure["kind"] == "runtime_mismatch"
        for failure in payload["strict_failures"]
    )


def test_cli_assert_strict_text_includes_strict_failure_summary(tmp_path: Path) -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate.environment_fingerprint["os"] = "strict-os-drift"

    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(baseline, baseline_path)
    write_artifact(candidate, candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--strict",
        ],
    )

    assert result.exit_code == 1
    assert "strict drift checks failed" in result.stdout


def test_cli_assert_requires_candidate() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
        ],
    )

    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "Provide --candidate PATH" in combined


def test_cli_assert_missing_file_returns_non_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "missing-baseline.rpk",
            "--candidate",
            "missing-candidate.rpk",
        ],
    )

    assert result.exit_code == 1


def test_cli_assert_guardrail_warn_mode_reports_findings(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(_guardrail_run("run-guardrail-base", "req-001"), baseline_path)
    write_artifact(_guardrail_run("run-guardrail-cand", "req-001"), candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--nondeterminism",
            "warn",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["nondeterminism"]["status"] == "warn"
    assert payload["nondeterminism"]["count"] >= 1


def test_cli_assert_guardrail_fail_mode_enforces_non_zero(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(_guardrail_run("run-guardrail-base", "req-001"), baseline_path)
    write_artifact(_guardrail_run("run-guardrail-cand", "req-001"), candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--nondeterminism",
            "fail",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["exit_code"] == 1
    assert payload["guardrail_failure"] is True
    assert payload["nondeterminism"]["status"] == "fail"


def test_cli_assert_guardrail_detects_diff_volatile_fields(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    baseline = _guardrail_run("run-guardrail-base", "req-001", uses_random=False)
    candidate = _guardrail_run("run-guardrail-cand", "req-001", uses_random=False)
    candidate.steps[1].output["timestamp"] = "2026-02-22T19:30:00Z"
    write_artifact(baseline, baseline_path)
    write_artifact(candidate, candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--nondeterminism",
            "warn",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["nondeterminism"]["count"] >= 1
    assert any(
        finding["source"] == "diff"
        for finding in payload["nondeterminism"]["findings"]
    )


def test_cli_assert_rejects_invalid_guardrail_mode() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
            "--nondeterminism",
            "invalid",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "Invalid nondeterminism mode" in combined


def test_cli_assert_slowdown_gate_passes_within_threshold(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(_timed_run("run-base", 100), baseline_path)
    write_artifact(_timed_run("run-cand", 110), candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--fail-on-slowdown",
            "15",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["performance"]["status"] == "within_threshold"
    assert payload["performance"]["gate_failed"] is False


def test_cli_assert_slowdown_gate_fails_when_exceeded(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(_timed_run("run-base", 100), baseline_path)
    write_artifact(_timed_run("run-cand", 140), candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--fail-on-slowdown",
            "10",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["slowdown_gate_failure"] is True
    assert payload["performance"]["status"] == "threshold_exceeded"
    assert payload["performance"]["gate_failed"] is True


def test_cli_assert_slowdown_gate_reports_missing_metrics(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.rpk"
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(_guardrail_run("run-base", "req-001", uses_random=False), baseline_path)
    write_artifact(_guardrail_run("run-cand", "req-001", uses_random=False), candidate_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "assert",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--fail-on-slowdown",
            "10",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["performance"]["status"] == "missing_metrics"
    assert payload["slowdown_gate_failure"] is True
