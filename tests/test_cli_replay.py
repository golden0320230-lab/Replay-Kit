import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_replay_writes_stub_artifact(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--seed",
            "11",
            "--fixed-clock",
            "2026-02-21T17:15:00Z",
        ],
    )

    assert result.exit_code == 0
    assert out.exists()

    replay_run = read_artifact(out)
    assert replay_run.runtime_versions["replay_mode"] == "stub"
    assert replay_run.runtime_versions["replay_seed"] == "11"
    assert replay_run.timestamp == "2026-02-21T17:15:00.000000Z"


def test_cli_replay_json_output_mode(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--seed",
            "5",
            "--fixed-clock",
            "2026-02-21T17:20:00Z",
            "--json",
        ],
    )

    assert result.exit_code == 0
    summary = json.loads(result.stdout.strip())
    assert summary["mode"] == "stub"
    assert summary["seed"] == 5
    assert summary["out"] == str(out)


def test_cli_replay_returns_non_zero_on_invalid_clock(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--fixed-clock",
            "2026-02-21T17:20:00",
        ],
    )

    assert result.exit_code == 1
    combined_output = result.stdout + result.stderr
    assert "replay failed" in combined_output
