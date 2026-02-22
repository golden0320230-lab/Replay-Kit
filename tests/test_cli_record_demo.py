import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_record_demo_writes_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "demo.rpk"

    runner = CliRunner()
    result = runner.invoke(app, ["record", "--out", str(out_path)])

    assert result.exit_code == 0
    assert out_path.exists()

    run = read_artifact(out_path)
    assert run.id == "run-demo-001"
    assert len(run.steps) == 6


def test_record_without_demo_flag_requires_target() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["record", "--no-demo"])

    assert result.exit_code == 2
    assert "--no-demo requires a target command" in result.output


def test_record_with_redaction_config_masks_custom_field(tmp_path: Path) -> None:
    out_path = tmp_path / "demo-custom.rpk"
    config_path = tmp_path / "redaction.json"
    config_path.write_text(
        json.dumps({"extra_sensitive_field_names": ["x-trace-id"]}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["record", "--out", str(out_path), "--redaction-config", str(config_path)],
    )

    assert result.exit_code == 0
    run = read_artifact(out_path)
    http_request_step = next(
        step
        for step in run.steps
        if step.type == "tool.request" and step.metadata.get("boundary") == "http"
    )
    assert http_request_step.input["headers"]["X-Trace-Id"] == "[REDACTED]"
