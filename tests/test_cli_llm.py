import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_llm_providers_lists_required_keys() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["llm", "providers"])

    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert "openai" in lines
    assert "anthropic" in lines
    assert "google" in lines


def test_cli_llm_providers_json_output() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["llm", "providers", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["artifact_path"] is None
    assert "openai" in payload["providers"]
    assert "anthropic" in payload["providers"]
    assert "google" in payload["providers"]


def test_cli_llm_fake_stream_writes_model_shaped_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "llm-fake.rpk"
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
    assert out_path.exists()

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata.get("provider") == "fake"
    assert run.steps[1].output["output"]["assembled_text"] == "Hello"


def test_cli_llm_openai_requires_api_key() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "openai",
        ],
    )

    assert result.exit_code == 2
    assert "OPENAI_API_KEY" in result.output


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
