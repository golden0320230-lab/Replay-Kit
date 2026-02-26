import json
import socket
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


BASELINE_FIXTURE = Path("examples/runs/passive_live_capture_golden.rpk")
CANDIDATE_FIXTURE = Path("examples/runs/passive_live_capture_candidate_diverged.rpk")


def test_live_capture_golden_fixture_is_sanitized_and_step_complete() -> None:
    assert BASELINE_FIXTURE.exists()
    assert CANDIDATE_FIXTURE.exists()

    run = read_artifact(BASELINE_FIXTURE)
    assert run.capture_mode == "passive"
    assert [step.type for step in run.steps] == [
        "model.request",
        "tool.response",
        "model.response",
        "tool.request",
        "model.request",
        "tool.response",
        "model.response",
    ]

    paths = [step.metadata.get("path") for step in run.steps if step.type.startswith("model.")]
    assert paths == ["/responses", "/responses", "/responses", "/responses"]
    assert all(step.metadata.get("response_source") == "upstream" for step in run.steps if step.type == "model.response")

    raw = BASELINE_FIXTURE.read_text(encoding="utf-8")
    assert "Authorization" not in raw
    assert "Bearer " not in raw
    assert "sk-" not in raw


def test_live_capture_fixture_stub_replay_is_deterministic_offline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    replay_a = tmp_path / "live-capture-replay-a.rpk"
    replay_b = tmp_path / "live-capture-replay-b.rpk"

    def _blocked_create_connection(*_args, **_kwargs):
        raise OSError("network disabled for live-capture replay parity test")

    monkeypatch.setattr(socket, "create_connection", _blocked_create_connection)

    replay_one = runner.invoke(
        app,
        [
            "replay",
            str(BASELINE_FIXTURE),
            "--out",
            str(replay_a),
            "--seed",
            "31",
            "--fixed-clock",
            "2026-02-26T00:00:00Z",
        ],
    )
    assert replay_one.exit_code == 0, replay_one.output

    replay_two = runner.invoke(
        app,
        [
            "replay",
            str(BASELINE_FIXTURE),
            "--out",
            str(replay_b),
            "--seed",
            "31",
            "--fixed-clock",
            "2026-02-26T00:00:00Z",
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
    assert payload["first_divergence"] is None
    assert payload["summary"] == {
        "changed": 0,
        "identical": 7,
        "missing_left": 0,
        "missing_right": 0,
    }


def test_live_capture_fixture_first_divergence_is_stable() -> None:
    runner = CliRunner()

    first = runner.invoke(
        app,
        [
            "diff",
            str(BASELINE_FIXTURE),
            str(CANDIDATE_FIXTURE),
            "--json",
        ],
    )
    second = runner.invoke(
        app,
        [
            "diff",
            str(BASELINE_FIXTURE),
            str(CANDIDATE_FIXTURE),
            "--json",
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    first_payload = json.loads(first.stdout.strip())
    second_payload = json.loads(second.stdout.strip())
    assert first_payload["first_divergence"] == second_payload["first_divergence"]

    divergence = first_payload["first_divergence"]
    assert divergence["index"] == 7
    assert divergence["left_step_id"] == "step-live-007"
    assert divergence["right_step_id"] == "step-live-007"
    assert divergence["left_type"] == "model.response"
    assert divergence["right_type"] == "model.response"
    assert first_payload["summary"] == {
        "changed": 1,
        "identical": 6,
        "missing_left": 0,
        "missing_right": 0,
    }
