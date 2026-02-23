import json

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_agent_capture_rejects_unsupported_agent() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "capture",
            "--agent",
            "unknown-agent",
            "--json",
            "--",
            "echo",
            "hello",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["exit_code"] == 2
    assert "unsupported agent" in payload["message"]


def test_cli_agent_providers_lists_registry_agents() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["agent", "providers", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert "codex" in payload["agents"]
    assert "claude-code" in payload["agents"]


def test_cli_agent_capture_requires_command_after_double_dash() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "capture",
            "--agent",
            "codex",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["exit_code"] == 2
    assert "missing command" in payload["message"]
