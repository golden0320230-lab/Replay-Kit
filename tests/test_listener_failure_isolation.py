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

    provider_cases = [
        (
            "/v1/chat/completions",
            {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            "openai",
        ),
        (
            "/v1/messages",
            {"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hello"}]},
            "anthropic",
        ),
        (
            "/v1beta/models/gemini-1.5-flash:generateContent",
            {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]},
            "google",
        ),
    ]

    try:
        for path, payload, _provider in provider_cases:
            degraded = requests.post(
                f"{base_url}{path}",
                json=payload,
                headers={"x-replaykit-capture-fail": "1"},
                timeout=2.0,
            )
            assert degraded.status_code == 200
            degraded_payload = degraded.json()
            assert degraded_payload["_replaykit"]["capture_status"] == "degraded"

            healthy = requests.post(
                f"{base_url}{path}",
                json=payload,
                timeout=2.0,
            )
            assert healthy.status_code == 200

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
        assert metrics["capture_errors"] >= 3
        assert metrics["degraded_responses"] >= 3
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
    assert len(error_steps) >= 3
    assert "degraded fallback response" in error_steps[-1].output["message"]
    seen_providers = {
        str(step.output.get("details", {}).get("provider"))
        for step in error_steps
    }
    assert seen_providers.issuperset({"openai", "anthropic", "google"})


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
