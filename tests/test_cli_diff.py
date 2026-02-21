import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_diff_text_first_divergence_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "diff",
            "examples/runs/m2_capture_boundaries.rpk",
            "examples/runs/m4_diverged_from_m2.rpk",
            "--first-divergence",
        ],
    )

    assert result.exit_code == 0
    assert "first divergence: step 3" in result.stdout
    assert "tool" in result.stdout


def test_cli_diff_json_output() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "diff",
            "examples/runs/m2_capture_boundaries.rpk",
            "examples/runs/m4_diverged_from_m2.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())

    assert payload["identical"] is False
    assert payload["first_divergence"]["index"] == 3


def test_cli_diff_identical_runs_message() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "diff",
            "examples/runs/m2_capture_boundaries.rpk",
            "examples/runs/m2_capture_boundaries.rpk",
        ],
    )

    assert result.exit_code == 0
    assert "no divergence detected" in result.stdout


def test_cli_diff_non_zero_on_missing_file() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "diff",
            "missing-left.rpk",
            "missing-right.rpk",
        ],
    )

    assert result.exit_code == 1
