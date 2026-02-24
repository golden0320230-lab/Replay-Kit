import json
import os
from pathlib import Path
import signal
import threading
import time

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact, read_artifact_envelope
from replaypack.cli.app import app
from replaypack.listener_state import is_pid_running


def _capture_openai_listener_trace(tmp_path: Path, name: str) -> Path:
    runner = CliRunner()
    state_file = tmp_path / f"{name}-state.json"
    out_path = tmp_path / f"{name}.rpk"

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"
    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello persistence"}],
            },
            timeout=2.0,
        )
        assert response.status_code == 200
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
    return out_path


def test_listener_persistence_step_hashes_stable_for_identical_traces(tmp_path: Path) -> None:
    left_path = _capture_openai_listener_trace(tmp_path, "left")
    right_path = _capture_openai_listener_trace(tmp_path, "right")

    left = read_artifact(left_path)
    right = read_artifact(right_path)

    assert [step.type for step in left.steps] == [step.type for step in right.steps]
    assert [step.hash for step in left.steps] == [step.hash for step in right.steps]


def test_listener_persistence_artifact_survives_abrupt_termination(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"
    request_error: list[str] = []

    start = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
        env={"REPLAYKIT_LISTENER_PERSIST_DELAY_SECONDS": "0.8"},
    )
    assert start.exit_code == 0, start.output
    started = json.loads(start.stdout.strip())
    pid = int(started["pid"])
    base_url = f"http://{started['host']}:{started['port']}"

    def _send_request() -> None:
        try:
            requests.post(
                f"{base_url}/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "abrupt shutdown"}],
                },
                timeout=3.0,
            )
        except Exception as error:  # pragma: no cover - platform-dependent timing
            request_error.append(str(error))

    request_thread = threading.Thread(target=_send_request, daemon=True)
    request_thread.start()
    time.sleep(0.1)

    if os.name == "nt":
        os.kill(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGKILL)

    deadline = time.time() + 5.0
    while time.time() < deadline and is_pid_running(pid):
        time.sleep(0.05)
    assert not is_pid_running(pid)

    request_thread.join(timeout=4.0)

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

    envelope = read_artifact_envelope(out_path)
    assert envelope["payload"]["run"]["source"] == "listener"
    run = read_artifact(out_path)
    assert run.source == "listener"
    assert run.capture_mode == "passive"
