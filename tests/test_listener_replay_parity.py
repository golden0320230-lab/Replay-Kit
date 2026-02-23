import json
import socket
from datetime import datetime
from pathlib import Path

import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app
from replaypack.diff import diff_runs
from replaypack.replay import ReplayConfig, write_replay_stub_artifact


def _capture_listener_fixture(tmp_path: Path, name: str) -> Path:
    runner = CliRunner()
    state_file = tmp_path / f"{name}-state.json"
    out_path = tmp_path / f"{name}.rpk"
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

        codex_events = requests.post(
            f"{base_url}/agent/codex/events",
            json={
                "events": [
                    {
                        "type": "model.request",
                        "input": {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
                    },
                    {
                        "type": "model.response",
                        "request_id": "req-codex-1",
                        "output": {"content": "hello"},
                    },
                ]
            },
            timeout=2.0,
        )
        assert codex_events.status_code == 202
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

    return out_path


def test_listener_generated_artifact_stub_replay_is_deterministic(tmp_path: Path) -> None:
    source_path = _capture_listener_fixture(tmp_path, "listener-source")
    source_run = read_artifact(source_path)

    replay_one = tmp_path / "listener-replay-1.rpk"
    replay_two = tmp_path / "listener-replay-2.rpk"
    config = ReplayConfig(seed=17, fixed_clock="2026-02-23T12:00:00Z")

    write_replay_stub_artifact(source_run, str(replay_one), config=config)
    write_replay_stub_artifact(source_run, str(replay_two), config=config)

    assert replay_one.read_bytes() == replay_two.read_bytes()
    diff = diff_runs(read_artifact(replay_one), read_artifact(replay_two))
    assert diff.identical is True
    assert diff.first_divergence is None


def test_listener_fixture_normalization_preserves_order_and_correlation(tmp_path: Path) -> None:
    left_path = _capture_listener_fixture(tmp_path, "listener-left")
    right_path = _capture_listener_fixture(tmp_path, "listener-right")
    left = read_artifact(left_path)
    right = read_artifact(right_path)

    assert [step.type for step in left.steps] == [step.type for step in right.steps]

    def _provider_correlation(run) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for step in run.steps:
            correlation_id = step.metadata.get("correlation_id")
            request_id = step.metadata.get("request_id")
            if isinstance(correlation_id, str) and isinstance(request_id, str):
                pairs.append((request_id, correlation_id))
        return pairs

    assert _provider_correlation(left) == _provider_correlation(right)

    for run in (left, right):
        parsed_timestamps = [
            datetime.fromisoformat(str(step.timestamp))
            for step in run.steps
            if step.timestamp
        ]
        assert parsed_timestamps == sorted(parsed_timestamps)


def test_listener_cli_stub_replay_offline_golden_assertions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = _capture_listener_fixture(tmp_path, "listener-cli-source")
    runner = CliRunner()

    replay_a = tmp_path / "listener-cli-replay-a.rpk"
    replay_b = tmp_path / "listener-cli-replay-b.rpk"

    # Stub replay should be fully offline; block outbound socket creation.
    def _blocked_create_connection(*_args, **_kwargs):
        raise OSError("network disabled for replay parity test")

    monkeypatch.setattr(socket, "create_connection", _blocked_create_connection)

    replay_one = runner.invoke(
        app,
        [
            "replay",
            str(source_path),
            "--out",
            str(replay_a),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay_one.exit_code == 0, replay_one.output

    replay_two = runner.invoke(
        app,
        [
            "replay",
            str(source_path),
            "--out",
            str(replay_b),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay_two.exit_code == 0, replay_two.output

    assert replay_a.read_bytes() == replay_b.read_bytes()

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_a),
            "--candidate",
            str(replay_b),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    payload = json.loads(assertion.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["exit_code"] == 0
    assert payload["first_divergence"] is None
    assert payload["summary"] == {
        "changed": 0,
        "identical": 6,
        "missing_left": 0,
        "missing_right": 0,
    }
