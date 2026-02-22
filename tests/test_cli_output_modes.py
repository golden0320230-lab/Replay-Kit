import json
import re
from pathlib import Path

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_quiet_suppresses_success_text(tmp_path: Path) -> None:
    out_path = tmp_path / "record.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--quiet",
            "record",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_cli_quiet_still_prints_errors() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--quiet",
            "replay",
            "examples/runs/m2_capture_boundaries.rpk",
            "--mode",
            "hybrid",
            "--rerun-type",
            "model.response",
        ],
    )

    assert result.exit_code == 2
    output = result.stdout + result.stderr
    assert "--rerun-from is required" in output


def test_cli_stable_json_default_is_compact() -> None:
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
    payload = json.loads(result.stdout)
    expected = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert result.stdout.strip() == expected


def test_cli_pretty_json_mode_is_multiline() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--pretty-json",
            "assert",
            "examples/runs/m2_capture_boundaries.rpk",
            "--candidate",
            "examples/runs/m2_capture_boundaries.rpk",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert "\n  \"" in result.stdout


def test_cli_no_color_mode_disables_ansi_sequences() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--no-color",
            "replay",
            "examples/runs/m2_capture_boundaries.rpk",
            "--mode",
            "invalid",
        ],
    )

    assert result.exit_code == 2
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    assert ansi_pattern.search(result.stdout + result.stderr) is None
