import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_listen_transparent_start_status_stop_cycle_json(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "darwin")
    monkeypatch.setattr("replaypack.cli.app._transparent_command_exists", lambda _name: True)
    monkeypatch.setattr("replaypack.cli.app._transparent_effective_uid", lambda: 0)

    start = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    assert started["status"] == "ok"
    assert started["running"] is True
    assert started["listener_session_id"].startswith("transparent-")

    status_running = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status_running.exit_code == 0, status_running.output
    running_payload = json.loads(status_running.stdout.strip())
    assert running_payload["status"] == "ok"
    assert running_payload["running"] is True
    assert running_payload["listener_session_id"] == started["listener_session_id"]

    stop = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert stop.exit_code == 0, stop.output
    stopped = json.loads(stop.stdout.strip())
    assert stopped["status"] == "ok"
    assert stopped["running"] is False

    status_stopped = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status_stopped.exit_code == 0, status_stopped.output
    stopped_payload = json.loads(status_stopped.stdout.strip())
    assert stopped_payload["running"] is False


def test_cli_listen_transparent_start_fails_when_not_macos(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "linux")

    result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "macOS required" in payload["message"]


def test_cli_listen_transparent_doctor_reports_not_ready_on_non_macos(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "linux")
    monkeypatch.setattr("replaypack.cli.app._transparent_command_exists", lambda _name: False)

    result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "doctor",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["ready"] is False
    platform_check = next(check for check in payload["checks"] if check["id"] == "platform.macos")
    assert platform_check["ok"] is False
    assert platform_check["required"] is True


def test_cli_listen_transparent_doctor_reports_ready_when_prereqs_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "darwin")
    monkeypatch.setattr("replaypack.cli.app._transparent_command_exists", lambda _name: True)
    monkeypatch.setattr("replaypack.cli.app._transparent_effective_uid", lambda: 0)

    result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "doctor",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["ready"] is True


def test_cli_listen_transparent_state_file_conflict_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "shared-state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "mode": "passive",
                "listener_session_id": "listener-conflict-001",
                "pid": 1,
            }
        ),
        encoding="utf-8",
    )

    status_result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "status",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert status_result.exit_code == 2, status_result.output
    status_payload = json.loads(status_result.stdout.strip())
    assert status_payload["status"] == "error"

    stop_result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert stop_result.exit_code == 2, stop_result.output
    stop_payload = json.loads(stop_result.stdout.strip())
    assert stop_payload["status"] == "error"


def test_cli_listen_transparent_start_records_rollback_handles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "darwin")
    monkeypatch.delenv("REPLAYKIT_TRANSPARENT_EXECUTE", raising=False)

    start = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    assert started["status"] == "ok"
    assert started["rollback_handle_count"] >= 1
    assert started["intercept_apply_executed"] is False

    state = json.loads(state_file.read_text(encoding="utf-8"))
    rollback_handles = state.get("rollback_handles")
    assert isinstance(rollback_handles, list)
    assert len(rollback_handles) >= 1

    stop = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert stop.exit_code == 0, stop.output
    stopped = json.loads(stop.stdout.strip())
    assert stopped["rollback_attempted"] == len(rollback_handles)


def test_cli_listen_transparent_status_cleans_stale_running_state(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "mode": "transparent",
                "listener_session_id": "transparent-stale-001",
                "pid": 999999,
                "rollback_handles": [
                    {"step_id": "pf.enable", "command": ["pfctl", "-d"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
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
    assert payload["rollback_attempted"] == 1
    assert not state_file.exists()


def test_cli_listen_transparent_start_cleans_stale_state_and_restarts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "mode": "transparent",
                "listener_session_id": "transparent-stale-start-001",
                "pid": 999999,
                "rollback_handles": [
                    {"step_id": "pf.enable", "command": ["pfctl", "-d"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("replaypack.cli.app._transparent_platform_name", lambda: "darwin")
    monkeypatch.delenv("REPLAYKIT_TRANSPARENT_EXECUTE", raising=False)

    start = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "start",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    payload = json.loads(start.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["running"] is True
    assert payload["stale_cleanup"] is True
    assert payload["rollback_attempted"] == 1

    stop = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert stop.exit_code == 0, stop.output


def test_cli_listen_transparent_stop_reports_rollback_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "transparent-state.json"
    state_file.write_text(
        json.dumps(
            {
                "status": "running",
                "mode": "transparent",
                "listener_session_id": "transparent-stop-fail-001",
                "pid": 0,
                "rollback_handles": [
                    {"step_id": "pf.enable", "command": ["pfctl", "-d"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    def _rollback_failure(_self, _handles):
        return {
            "ok": False,
            "attempted": 1,
            "failures": [
                {
                    "step_id": "pf.enable",
                    "command": ["pfctl", "-d"],
                    "returncode": 1,
                    "stderr": "permission denied",
                }
            ],
        }

    monkeypatch.setattr("replaypack.cli.app.TransparentMacOSController.rollback", _rollback_failure)

    result = runner.invoke(
        app,
        [
            "listen",
            "transparent",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["rollback_attempted"] == 1
    assert payload["rollback_failures"]
    assert state_file.exists()
