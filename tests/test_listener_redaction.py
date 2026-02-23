import json
from pathlib import Path

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_listener_persistence_redacts_provider_and_agent_secrets(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-redaction.rpk"

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

    provider_secret = "sk-1234567890abcdefghij"
    header_secret = "header-token-should-not-persist"
    agent_secret = "agent-super-secret-token"

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {provider_secret}",
                "X-Custom-Token": header_secret,
                "X-Request-Id": "req-visible-1",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": f"use key {provider_secret}"}],
                "api_key": provider_secret,
            },
            timeout=2.0,
        )
        assert response.status_code == 200

        agent_response = requests.post(
            f"{base_url}/agent/codex/events",
            json={
                "events": [
                    {
                        "type": "tool.response",
                        "tool": "shell",
                        "output": {"token": agent_secret, "stdout": "ok"},
                    }
                ]
            },
            timeout=2.0,
        )
        assert agent_response.status_code == 202
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
    request_step = run.steps[0]
    assert request_step.type == "model.request"
    assert request_step.input["model"] == "gpt-4o-mini"
    assert request_step.input["headers"]["authorization"] == "[REDACTED]"
    assert request_step.input["headers"]["x-custom-token"] == "[REDACTED]"
    assert request_step.input["headers"]["x-request-id"] == "req-visible-1"
    assert request_step.input["payload"]["api_key"] == "[REDACTED]"
    assert "[REDACTED]" in request_step.input["payload"]["messages"][0]["content"]

    tool_response_step = next(step for step in run.steps if step.type == "tool.response")
    assert tool_response_step.output["event"]["token"] == "[REDACTED]"
    assert tool_response_step.output["event"]["stdout"] == "ok"

    artifact_text = out_path.read_text(encoding="utf-8")
    assert provider_secret not in artifact_text
    assert header_secret not in artifact_text
    assert agent_secret not in artifact_text
