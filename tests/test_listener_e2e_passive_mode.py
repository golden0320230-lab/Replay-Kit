import json
from pathlib import Path

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def _start_listener(runner: CliRunner, *, state_file: Path, out_path: Path) -> tuple[str, int]:
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
    payload = json.loads(start.stdout.strip())
    return str(payload["host"]), int(payload["port"])


def _stop_listener(runner: CliRunner, *, state_file: Path) -> None:
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


def test_passive_listener_e2e_non_stream_capture_replay_assert(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    capture_path = tmp_path / "listener-capture.rpk"
    replay_path = tmp_path / "listener-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            timeout=2.0,
        )
        assert openai.status_code == 200

        anthropic = requests.post(
            f"{base_url}/v1/messages",
            json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hello"}]},
            timeout=2.0,
        )
        assert anthropic.status_code == 200
    finally:
        _stop_listener(runner, state_file=state_file)

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    source_run = read_artifact(capture_path)
    replay_run = read_artifact(replay_path)
    assert [step.type for step in source_run.steps] == [step.type for step in replay_run.steps]

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["changed"] == 0
    assert summary["summary"]["missing_left"] == 0
    assert summary["summary"]["missing_right"] == 0


def test_passive_listener_e2e_stream_capture_replay_assert(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-stream-state.json"
    capture_path = tmp_path / "listener-stream-capture.rpk"
    replay_path = tmp_path / "listener-stream-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        openai_stream = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "stream hello"}],
                "stream": True,
            },
            timeout=2.0,
        )
        assert openai_stream.status_code == 200

        anthropic_stream = requests.post(
            f"{base_url}/v1/messages",
            json={
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": "stream hello"}],
                "stream": True,
            },
            timeout=2.0,
        )
        assert anthropic_stream.status_code == 200
    finally:
        _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    stream_requests = [
        step
        for step in run.steps
        if step.type == "model.request" and bool(step.input.get("payload", {}).get("stream"))
    ]
    assert len(stream_requests) >= 2

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    replay_run = read_artifact(replay_path)
    assert [step.type for step in run.steps] == [step.type for step in replay_run.steps]

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["changed"] == 0


def test_passive_listener_e2e_openai_responses_routes(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-responses-state.json"
    capture_path = tmp_path / "listener-responses-capture.rpk"
    replay_path = tmp_path / "listener-responses-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        responses = requests.post(
            f"{base_url}/responses",
            json={"model": "gpt-5.3-codex", "input": "say hello"},
            timeout=2.0,
        )
        assert responses.status_code == 200
        responses_payload = responses.json()
        assert responses_payload["object"] == "response"
        assert responses_payload["status"] == "completed"

        v1_responses = requests.post(
            f"{base_url}/v1/responses",
            json={"model": "gpt-5.3-codex", "input": "say hello again"},
            timeout=2.0,
        )
        assert v1_responses.status_code == 200
        v1_payload = v1_responses.json()
        assert v1_payload["object"] == "response"
        assert v1_payload["status"] == "completed"
    finally:
        _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    assert [step.metadata.get("path") for step in run.steps] == [
        "/responses",
        "/responses",
        "/v1/responses",
        "/v1/responses",
    ]
    assert [step.metadata.get("provider") for step in run.steps] == [
        "openai",
        "openai",
        "openai",
        "openai",
    ]

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["identical"] == 4
