import json
from pathlib import Path

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app
from replaypack.listener_gateway import detect_provider


def test_listener_gateway_detect_provider_paths() -> None:
    assert detect_provider("/v1/chat/completions") == "openai"
    assert detect_provider("/v1/messages") == "anthropic"
    assert detect_provider("/v1beta/models/gemini-1.5-flash:generateContent") == "google"
    assert detect_provider("/v1/unknown") is None


def test_listener_gateway_captures_openai_anthropic_google_steps(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

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
        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            timeout=2.0,
        )
        assert openai.status_code == 200

        anthropic = requests.post(
            f"{base_url}/v1/messages",
            json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]},
            timeout=2.0,
        )
        assert anthropic.status_code == 200

        google = requests.post(
            f"{base_url}/v1beta/models/gemini-1.5-flash:generateContent",
            json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            timeout=2.0,
        )
        assert google.status_code == 200
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
    assert run.source == "listener"
    assert run.capture_mode == "passive"
    assert run.listener_session_id == started["listener_session_id"]
    assert run.listener_bind == {"host": started["host"], "port": started["port"]}
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    providers = [step.metadata.get("provider") for step in run.steps]
    assert providers == ["openai", "openai", "anthropic", "anthropic", "google", "google"]


def test_listener_gateway_error_path_returns_502_and_captures_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

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
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-replaykit-fail": "forced-failure"},
            timeout=2.0,
        )
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["type"] == "listener_gateway_error"
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
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    response_step = run.steps[-1]
    assert response_step.output["status_code"] == 502
    assert response_step.output["error"] == {
        "message": "forced-failure",
        "type": "gateway_error",
    }
