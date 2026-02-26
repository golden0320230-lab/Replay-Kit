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
    assert started["allow_synthetic"] is True
    assert started["synthetic_policy"] == "allow"
    assert started["payload_string_limit"] == 4096
    assert started["full_payload_capture"] is False

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
    assert running_payload["allow_synthetic"] is True
    assert running_payload["synthetic_policy"] == "allow"
    assert running_payload["payload_string_limit"] == 4096
    assert running_payload["full_payload_capture"] is False

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


def test_cli_listen_start_cleans_stale_pid_state(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    stale_pid = 999999
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "listener_session_id": "listener-stale-start-001",
                "pid": stale_pid,
                "host": "127.0.0.1",
                "port": 9011,
                "artifact_path": str(tmp_path / "stale.rpk"),
            }
        ),
        encoding="utf-8",
    )

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
    payload = json.loads(start.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["stale_cleanup"] is True
    assert payload["pid"] > 0
    assert payload["pid"] != stale_pid
    assert payload["listener_session_id"] != "listener-stale-start-001"

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


def test_cli_listen_start_with_fail_on_synthetic_exposes_policy(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--fail-on-synthetic",
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    assert started["allow_synthetic"] is False
    assert started["synthetic_policy"] == "fail_closed"
    assert started["payload_string_limit"] == 4096
    assert started["full_payload_capture"] is False

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
    running_payload = json.loads(status.stdout.strip())
    assert running_payload["allow_synthetic"] is False
    assert running_payload["synthetic_policy"] == "fail_closed"
    assert running_payload["payload_string_limit"] == 4096
    assert running_payload["full_payload_capture"] is False

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


def test_cli_listen_start_with_best_effort_policy_exposes_runtime_controls(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--fallback-policy",
            "best_effort",
            "--upstream-timeout-seconds",
            "1.5",
            "--upstream-retries",
            "2",
            "--upstream-retry-backoff-seconds",
            "0.0",
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    assert started["fallback_policy"] == "best_effort"
    assert started["allow_synthetic"] is False
    assert started["synthetic_policy"] == "fail_closed"
    assert started["upstream_timeout_seconds"] == 1.5
    assert started["upstream_retries"] == 2
    assert started["upstream_retry_backoff_seconds"] == 0.0

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
    running_payload = json.loads(status.stdout.strip())
    assert running_payload["fallback_policy"] == "best_effort"
    assert running_payload["upstream_timeout_seconds"] == 1.5
    assert running_payload["upstream_retries"] == 2
    assert running_payload["upstream_retry_backoff_seconds"] == 0.0

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


def test_cli_listen_start_with_full_payload_capture_exposes_policy(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--full-payload-capture",
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    assert started["payload_string_limit"] == 0
    assert started["full_payload_capture"] is True

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
    running_payload = json.loads(status.stdout.strip())
    assert running_payload["payload_string_limit"] == 0
    assert running_payload["full_payload_capture"] is True

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
