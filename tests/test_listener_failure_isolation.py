import json
from pathlib import Path

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_listener_provider_capture_failure_serves_degraded_fallback(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-failure.rpk"

    start_result = runner.invoke(
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
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            headers={"x-replaykit-capture-fail": "1"},
            timeout=2.0,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["_replaykit"]["capture_status"] == "degraded"

        status_result = runner.invoke(
            app,
            [
                "listen",
                "status",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert status_result.exit_code == 0, status_result.output
        status_payload = json.loads(status_result.stdout.strip())
        assert status_payload["running"] is True
        metrics = status_payload["health"]["metrics"]
        assert metrics["capture_errors"] >= 1
        assert metrics["degraded_responses"] >= 1
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    error_steps = [
        step
        for step in run.steps
        if step.type == "error.event" and step.metadata.get("category") == "capture_failure"
    ]
    assert error_steps
    assert "degraded fallback response" in error_steps[-1].output["message"]


def test_listener_agent_malformed_frames_increment_dropped_metrics(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-failure-agent.rpk"

    start_result = runner.invoke(
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
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        malformed = requests.post(
            f"{base_url}/agent/codex/events",
            data="not-json",
            headers={"Content-Type": "application/json"},
            timeout=2.0,
        )
        assert malformed.status_code == 202
        malformed_payload = malformed.json()
        assert malformed_payload["dropped"] >= 1
        assert malformed_payload["metrics"]["dropped_events"] >= 1

        status_result = runner.invoke(
            app,
            [
                "listen",
                "status",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert status_result.exit_code == 0, status_result.output
        status_payload = json.loads(status_result.stdout.strip())
        assert status_payload["health"]["metrics"]["dropped_events"] >= 1
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output
