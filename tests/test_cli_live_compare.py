import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import write_artifact
from replaypack.capture import build_demo_run
from replaypack.cli.app import app


def test_cli_live_compare_live_demo_passes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.rpk"
    live_out = tmp_path / "live.rpk"
    write_artifact(build_demo_run(), baseline)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            str(baseline),
            "--out",
            str(live_out),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["first_divergence"] is None
    assert payload["live_mode"] == "demo"
    assert payload["candidate_path"] == str(live_out)
    assert live_out.exists()


def test_cli_live_compare_fails_with_candidate_divergence_json() -> None:
    baseline = Path("examples/runs/m2_capture_boundaries.rpk")
    candidate = Path("examples/runs/m4_diverged_from_m2.rpk")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            str(baseline),
            "--candidate",
            str(candidate),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["first_divergence"] is not None
    assert payload["first_divergence"]["index"] == 3
    assert payload["candidate_path"] == str(candidate)


def test_cli_live_compare_fails_with_candidate_divergence_text() -> None:
    baseline = Path("examples/runs/m2_capture_boundaries.rpk")
    candidate = Path("examples/runs/m4_diverged_from_m2.rpk")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            str(baseline),
            "--candidate",
            str(candidate),
        ],
    )

    assert result.exit_code == 1
    output = result.stdout + result.stderr
    assert "live-compare failed: divergence detected" in output
    assert "first divergence:" in output


def test_cli_live_compare_requires_candidate_or_live_demo() -> None:
    baseline = Path("examples/runs/m2_capture_boundaries.rpk")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            str(baseline),
            "--no-live-demo",
        ],
    )

    assert result.exit_code == 2
    output = result.stdout + result.stderr
    assert "missing live input" in output


def test_cli_live_compare_returns_error_for_missing_baseline_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            "does/not/exist.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "live-compare failed" in payload["message"]


def test_cli_live_compare_returns_error_for_missing_candidate_json() -> None:
    baseline = Path("examples/runs/m2_capture_boundaries.rpk")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "live-compare",
            str(baseline),
            "--candidate",
            "does/not/exist.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "live-compare failed" in payload["message"]
