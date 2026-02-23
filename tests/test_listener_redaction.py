import json
from pathlib import Path
import re

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


_KNOWN_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"agent-super-secret-token"),
    re.compile(r"header-token-should-not-persist"),
)


def _scan_for_known_secrets(text: str) -> list[str]:
    matches: list[str] = []
    for pattern in _KNOWN_SECRET_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches


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
    aws_secret = "AKIA1234567890ABCDEF"
    header_secret = "header-token-should-not-persist"
    agent_secret = "agent-super-secret-token"

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions?api_key={provider_secret}&aws={aws_secret}",
            headers={
                "Authorization": f"Bearer {provider_secret}",
                "X-Custom-Token": header_secret,
                "X-Request-Id": "req-visible-1",
            },
            json={
                "model": "gpt-4o-mini",
                "stream": True,
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
    assert request_step.input["query"]["api_key"] == "[REDACTED]"
    assert request_step.input["query"]["aws"] == "[REDACTED]"

    tool_response_step = next(step for step in run.steps if step.type == "tool.response")
    assert tool_response_step.output["event"]["token"] == "[REDACTED]"
    assert tool_response_step.output["event"]["stdout"] == "ok"

    artifact_text = out_path.read_text(encoding="utf-8")
    assert provider_secret not in artifact_text
    assert aws_secret not in artifact_text
    assert header_secret not in artifact_text
    assert agent_secret not in artifact_text
    assert not _scan_for_known_secrets(artifact_text)


def test_listener_redaction_masks_failure_message_and_scanner_detects_known_leaks(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-redaction-failure.rpk"

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

    failure_secret = "sk-aaaaaaaaaaaaaaaaaaaaaa"
    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"x-replaykit-fail": failure_secret},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            timeout=2.0,
        )
        assert response.status_code == 502
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
    response_step = run.steps[-1]
    assert response_step.type == "model.response"
    assert response_step.output["error"]["message"] == "[REDACTED]"

    artifact_text = out_path.read_text(encoding="utf-8")
    assert failure_secret not in artifact_text
    assert not _scan_for_known_secrets(artifact_text)

    synthetic_leak = (
        "Authorization: Bearer sk-1234567890abcdefghij\n"
        "aws=AKIA1234567890ABCDEF\n"
        "agent-super-secret-token\n"
    )
    findings = _scan_for_known_secrets(synthetic_leak)
    assert len(findings) == 3
