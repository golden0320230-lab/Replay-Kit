import json
import os
from pathlib import Path
import socket

from typer.testing import CliRunner

from replaypack.cli.app import app


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_listener_start_stop_stress_cycles_leave_no_stale_state(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    for _ in range(5):
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
        assert not state_file.exists()

    status = runner.invoke(
        app,
        [
            "listen",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status.exit_code == 0, status.output
    payload = json.loads(status.stdout.strip())
    assert payload["running"] is False


def test_listener_releases_explicit_port_after_stop(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    port = _free_port()

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output

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

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.5)
        result = probe.connect_ex(("127.0.0.1", port))
    finally:
        probe.close()
    assert result != 0


def test_listen_env_command_does_not_mutate_process_environment(tmp_path: Path) -> None:
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

    before = dict(os.environ)
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

    after = dict(os.environ)
    assert before == after
