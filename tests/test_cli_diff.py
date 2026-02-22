import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import write_artifact
from replaypack.cli.app import app
from replaypack.core.models import Run, Step


def _write_diff_fixture(path: Path, *, run_id: str, session_id: str) -> None:
    run = Run(
        id=run_id,
        timestamp="2026-02-22T00:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.1", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-000001",
                type="tool.request",
                input={"session_id": session_id, "stable": "yes"},
                output={"status": "ok"},
                metadata={"tool": "demo"},
            ).with_hash(),
        ],
    )
    write_artifact(run, path)


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


def test_cli_diff_redaction_config_masks_custom_fields(tmp_path: Path) -> None:
    left = tmp_path / "left.rpk"
    right = tmp_path / "right.rpk"
    config = tmp_path / "redaction.json"
    _write_diff_fixture(left, run_id="run-left", session_id="left-secret")
    _write_diff_fixture(right, run_id="run-right", session_id="right-secret")
    config.write_text(
        json.dumps({"extra_sensitive_field_names": ["session_id"]}),
        encoding="utf-8",
    )

    runner = CliRunner()
    baseline_result = runner.invoke(
        app,
        ["diff", str(left), str(right), "--json"],
    )
    redacted_result = runner.invoke(
        app,
        [
            "diff",
            str(left),
            str(right),
            "--json",
            "--redaction-config",
            str(config),
        ],
    )

    assert baseline_result.exit_code == 0
    assert redacted_result.exit_code == 0
    baseline_payload = json.loads(baseline_result.stdout.strip())
    redacted_payload = json.loads(redacted_result.stdout.strip())
    assert baseline_payload["identical"] is False
    assert redacted_payload["identical"] is True
    assert "left-secret" not in redacted_result.stdout
    assert "right-secret" not in redacted_result.stdout
