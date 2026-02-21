import json

from typer.testing import CliRunner

from replaypack.cli.app import app


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
