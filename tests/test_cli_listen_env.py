import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_listen_env_outputs_bash_exports(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output

    try:
        env_result = runner.invoke(
            app,
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
            ],
        )
        assert env_result.exit_code == 0, env_result.output
        assert "export REPLAYKIT_LISTENER_URL=" in env_result.stdout
        assert "export OPENAI_BASE_URL=" in env_result.stdout
        assert "OPENAI_API_KEY" not in env_result.stdout
    finally:
        stop = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop.exit_code == 0, stop.output


def test_cli_listen_env_json_and_powershell_modes(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())

    try:
        json_result = runner.invoke(
            app,
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert json_result.exit_code == 0, json_result.output
        payload = json.loads(json_result.stdout.strip())
        assert payload["status"] == "ok"
        assert payload["env"]["REPLAYKIT_LISTENER_URL"] == (
            f"http://{started['host']}:{started['port']}"
        )
        assert "never API keys" in payload["usage_note"]

        ps_result = runner.invoke(
            app,
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
                "--shell",
                "powershell",
            ],
        )
        assert ps_result.exit_code == 0, ps_result.output
        assert "$env:REPLAYKIT_LISTENER_URL" in ps_result.stdout
    finally:
        stop = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop.exit_code == 0, stop.output


def test_cli_listen_env_fails_when_listener_not_running(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    result = runner.invoke(
        app,
        [
            "listen",
            "env",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "not running" in payload["message"]
