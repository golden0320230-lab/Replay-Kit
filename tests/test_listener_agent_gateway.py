import json
from pathlib import Path
import subprocess
import sys

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app
from replaypack.listener_agent_gateway import detect_agent, normalize_agent_events


def test_listener_agent_gateway_detect_and_normalize() -> None:
    assert detect_agent("/agent/codex/events") == "codex"
    assert detect_agent("/agent/claude-code/events") == "claude-code"
    assert detect_agent("/agent/unknown/events") is None

    events, dropped = normalize_agent_events(
        agent="codex",
        payload={
            "events": [
                {"type": "model.request", "input": {"model": "gpt-4o-mini"}},
                {
                    "type": "model.response",
                    "request_id": "req-1",
                    "output": {"content": "Hello"},
                },
            ]
        },
    )
    assert dropped == 0
    assert [event["step_type"] for event in events] == [
        "model.request",
        "model.response",
    ]


def test_listener_agent_gateway_captures_codex_and_claude_events(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-agent-capture.rpk"

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
        codex = requests.post(
            f"{base_url}/agent/codex/events",
            json={
                "events": [
                    {
                        "type": "model.request",
                        "input": {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
                        "metadata": {"provider": "openai"},
                    },
                    {
                        "type": "model.response",
                        "request_id": "req-codex-1",
                        "output": {"content": "hello"},
                        "metadata": {"provider": "openai"},
                    },
                ]
            },
            timeout=2.0,
        )
        assert codex.status_code == 202
        codex_payload = codex.json()
        assert codex_payload["captured"] == 2
        assert codex_payload["dropped"] == 0

        claude = requests.post(
            f"{base_url}/agent/claude-code/events",
            json=[
                {"type": "tool.request", "input": {"tool": "read_file", "args": ["README.md"]}},
                {"type": "tool.response", "tool": "read_file", "output": {"ok": True}},
            ],
            timeout=2.0,
        )
        assert claude.status_code == 202
        claude_payload = claude.json()
        assert claude_payload["captured"] == 2
        assert claude_payload["dropped"] == 0

        malformed = requests.post(
            f"{base_url}/agent/codex/events",
            data="not-json",
            headers={"Content-Type": "application/json"},
            timeout=2.0,
        )
        assert malformed.status_code == 202
        malformed_payload = malformed.json()
        assert malformed_payload["captured"] == 0
        assert malformed_payload["dropped"] >= 1
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
    step_types = [step.type for step in run.steps]
    assert "model.request" in step_types
    assert "model.response" in step_types
    assert "tool.request" in step_types
    assert "tool.response" in step_types
    assert "error.event" in step_types
    agents = {step.metadata.get("agent") for step in run.steps if step.metadata.get("agent")}
    assert {"codex", "claude-code"} <= agents


def test_listener_agent_gateway_jsonl_fixture_ingestion_and_parse_diagnostics(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-agent-jsonl.rpk"

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

    codex_fixture = Path("tests/fixtures/agents/fake_codex_agent.py")
    claude_fixture = Path("tests/fixtures/agents/fake_claude_code_agent.py")
    codex_jsonl = subprocess.run(
        [sys.executable, str(codex_fixture)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    claude_jsonl = subprocess.run(
        [sys.executable, str(claude_fixture)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    try:
        codex = requests.post(
            f"{base_url}/agent/codex/events",
            data=codex_jsonl,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=2.0,
        )
        assert codex.status_code == 202
        codex_payload = codex.json()
        assert codex_payload["captured"] == 4
        assert codex_payload["dropped"] == 0
        assert codex_payload["parse_error"] is None

        claude = requests.post(
            f"{base_url}/agent/claude-code/events",
            data=claude_jsonl,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=2.0,
        )
        assert claude.status_code == 202
        claude_payload = claude.json()
        assert claude_payload["captured"] == 4
        assert claude_payload["dropped"] == 0
        assert claude_payload["parse_error"] is None

        malformed = requests.post(
            f"{base_url}/agent/codex/events",
            data='{"type":"model.request","input":{"model":"gpt-4o-mini"}}\n{bad-json}\n',
            headers={"Content-Type": "application/x-ndjson"},
            timeout=2.0,
        )
        assert malformed.status_code == 202
        malformed_payload = malformed.json()
        assert malformed_payload["captured"] == 1
        assert malformed_payload["dropped"] >= 1
        assert malformed_payload["parse_error"] == "jsonl_partial_parse"
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
    listener_parse_errors = [
        step
        for step in run.steps
        if step.type == "error.event" and step.metadata.get("category") == "agent_parse_failure"
    ]
    assert listener_parse_errors
    latest = listener_parse_errors[-1]
    assert latest.output["details"]["agent"] == "codex"
    assert latest.output["details"]["reason"] == "jsonl_partial_parse"
    assert int(latest.output["details"]["dropped_frames"]) >= 1
