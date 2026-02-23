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


def test_cli_listen_env_bash_output_is_deterministic_and_copy_safe(tmp_path: Path) -> None:
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
        first = runner.invoke(
            app,
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
                "--shell",
                "bash",
            ],
        )
        second = runner.invoke(
            app,
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
                "--shell",
                "bash",
            ],
        )
        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert first.stdout == second.stdout

        lines = first.stdout.strip().splitlines()
        assert len(lines) == 7
        assert lines[0] == "# ReplayKit passive listener routing exports (no secrets)"
        assert lines[1].startswith("export REPLAYKIT_LISTENER_URL='http://127.0.0.1:")
        assert lines[1].endswith("'")
        assert lines[2:] == [
            "export OPENAI_BASE_URL=\"$REPLAYKIT_LISTENER_URL\"",
            "export ANTHROPIC_BASE_URL=\"$REPLAYKIT_LISTENER_URL\"",
            "export GEMINI_BASE_URL=\"$REPLAYKIT_LISTENER_URL\"",
            "export REPLAYKIT_CODEX_EVENTS_URL=\"$REPLAYKIT_LISTENER_URL/agent/codex/events\"",
            "export REPLAYKIT_CLAUDE_CODE_EVENTS_URL=\"$REPLAYKIT_LISTENER_URL/agent/claude-code/events\"",
        ]
        assert "OPENAI_API_KEY" not in first.stdout
        assert "ANTHROPIC_API_KEY" not in first.stdout
        assert "GEMINI_API_KEY" not in first.stdout
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


def test_cli_listen_env_powershell_output_is_deterministic(tmp_path: Path) -> None:
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
        first = runner.invoke(
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
        second = runner.invoke(
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
        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert first.stdout == second.stdout

        lines = first.stdout.strip().splitlines()
        assert len(lines) == 7
        assert lines[0] == "# ReplayKit passive listener routing exports (no secrets)"
        assert lines[1].startswith("$env:REPLAYKIT_LISTENER_URL = 'http://127.0.0.1:")
        assert lines[1].endswith("'")
        assert lines[2:] == [
            "$env:OPENAI_BASE_URL = $env:REPLAYKIT_LISTENER_URL",
            "$env:ANTHROPIC_BASE_URL = $env:REPLAYKIT_LISTENER_URL",
            "$env:GEMINI_BASE_URL = $env:REPLAYKIT_LISTENER_URL",
            "$env:REPLAYKIT_CODEX_EVENTS_URL = $env:REPLAYKIT_LISTENER_URL + '/agent/codex/events'",
            "$env:REPLAYKIT_CLAUDE_CODE_EVENTS_URL = $env:REPLAYKIT_LISTENER_URL + '/agent/claude-code/events'",
        ]
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
