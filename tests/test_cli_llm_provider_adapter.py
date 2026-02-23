import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_llm_fake_stream_uses_provider_adapter_capture_shape(tmp_path: Path) -> None:
    out_path = tmp_path / "llm-fake-stream.rpk"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "fake",
            "--model",
            "fake-chat",
            "--prompt",
            "say hello",
            "--stream",
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["provider"] == "fake"
    assert payload["api_key_present"] is False

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata.get("adapter_name") == "fake.provider-adapter"
    assert run.steps[1].metadata.get("adapter_name") == "fake.provider-adapter"
    assert run.steps[1].output["output"]["assembled_text"] == "Hello"
    assert len(run.steps[1].output["output"]["chunks"]) == 2


def test_cli_llm_rejects_unknown_provider() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "unknown",
        ],
    )

    assert result.exit_code == 2
    assert "unsupported provider" in result.output
