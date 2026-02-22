import json
from pathlib import Path
import socket

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_e2e_record_replay_assert_golden_path(tmp_path: Path, monkeypatch) -> None:
    source_artifact = tmp_path / "tmp.rpk"
    runner = CliRunner()

    record_result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(source_artifact),
            "--",
            "python",
            "examples/apps/minimal_app.py",
        ],
    )
    assert record_result.exit_code == 0, record_result.output
    assert source_artifact.exists()

    blocked_network_calls: list[object] = []

    def _blocked_create_connection(address: object, *args: object, **kwargs: object):
        blocked_network_calls.append(address)
        raise AssertionError(f"Unexpected network call during replay: {address}")

    def _blocked_socket_connect(self: socket.socket, address: object) -> None:
        blocked_network_calls.append(address)
        raise AssertionError(f"Unexpected network call during replay: {address}")

    monkeypatch.setattr(socket, "create_connection", _blocked_create_connection)
    monkeypatch.setattr(socket.socket, "connect", _blocked_socket_connect, raising=True)

    replay_hashes: set[tuple[str | None, ...]] = set()
    for index in range(10):
        replay_artifact = tmp_path / f"replay-{index}.rpk"
        replay_result = runner.invoke(
            app,
            [
                "replay",
                str(source_artifact),
                "--out",
                str(replay_artifact),
                "--seed",
                "13",
                "--fixed-clock",
                "2026-02-22T00:00:00Z",
            ],
        )
        assert replay_result.exit_code == 0, replay_result.output
        replay_run = read_artifact(replay_artifact)
        replay_hashes.add(tuple(step.hash for step in replay_run.steps))

    assert len(replay_hashes) == 1
    assert blocked_network_calls == []

    assert_result = runner.invoke(
        app,
        [
            "assert",
            str(source_artifact),
            "--candidate",
            str(source_artifact),
            "--json",
        ],
    )
    assert assert_result.exit_code == 0, assert_result.output
    payload = json.loads(assert_result.stdout.strip())
    assert payload["status"] == "pass"
