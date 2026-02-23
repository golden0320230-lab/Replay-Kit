import json
from pathlib import Path
import socket

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_listen_start_status_stop_cycle_json(tmp_path: Path) -> None:
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
    assert started["status"] == "ok"
    assert started["listener_session_id"]
    assert started["pid"] > 0
    assert started["port"] > 0

    status_running = runner.invoke(
        app,
        [
            "listen",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status_running.exit_code == 0, status_running.output
    running_payload = json.loads(status_running.stdout.strip())
    assert running_payload["running"] is True
    assert running_payload["listener_session_id"] == started["listener_session_id"]
    assert running_payload["pid"] == started["pid"]
    assert running_payload["healthy"] is True

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
    stopped = json.loads(stop.stdout.strip())
    assert stopped["status"] == "ok"
    assert "stopped" in stopped["message"]

    status_stopped = runner.invoke(
        app,
        [
            "listen",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status_stopped.exit_code == 0, status_stopped.output
    stopped_payload = json.loads(status_stopped.stdout.strip())
    assert stopped_payload["running"] is False


def test_cli_listen_status_cleans_stale_pid_state(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "listener_session_id": "listener-stale-001",
                "pid": 999999,
                "host": "127.0.0.1",
                "port": 9000,
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "listen",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["running"] is False
    assert payload["stale_cleanup"] is True
    assert not state_file.exists()


def test_cli_listen_start_rejects_port_conflict(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])

    try:
        result = runner.invoke(
            app,
            [
                "listen",
                "start",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
    finally:
        sock.close()

    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "unavailable" in payload["message"]


def test_cli_listen_stop_when_already_stopped_is_idempotent(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    result = runner.invoke(
        app,
        [
            "listen",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert "already stopped" in payload["message"]
