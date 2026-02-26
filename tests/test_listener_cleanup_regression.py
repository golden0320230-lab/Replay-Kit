import json
import os
from pathlib import Path
import socket

import requests
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


def test_listener_rotation_retention_limits_artifact_growth(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--rotation-max-steps",
            "4",
            "--retention-max-artifacts",
            "2",
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        for index in range(6):
            response = requests.post(
                f"{base_url}/responses",
                json={"model": "gpt-5.3-codex", "input": f"rotation-{index}"},
                timeout=2.0,
            )
            assert response.status_code == 200

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
        status_payload = json.loads(status.stdout.strip())
        metrics = status_payload["health"]["metrics"]
        assert metrics["rotation_max_steps"] == 4
        assert metrics["retention_max_artifacts"] == 2
        assert metrics["rotated_artifacts"] >= 3
        assert metrics["retained_rotation_artifacts"] <= 2
        assert metrics["retention_pruned_artifacts"] >= 1
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

    rotated = sorted(tmp_path.glob("listener-capture.part-*.rpk"))
    assert len(rotated) <= 2
    assert out_path.exists()
