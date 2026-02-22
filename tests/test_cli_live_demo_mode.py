from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app
from replaypack.replay import ReplayConfig, replay_stub_run


def test_live_demo_stream_mode_writes_model_shaped_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "live-demo.rpk"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "live-demo",
            "--out",
            str(out_path),
            "--provider",
            "fake",
            "--stream",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert out_path.exists()
    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata.get("provider") == "fake"
    assert run.steps[1].output["output"]["stream"] is True
    assert run.steps[1].output["output"]["assembled_text"] == "Hello"


def test_live_demo_replay_hash_is_stable_over_50_runs(tmp_path: Path) -> None:
    out_path = tmp_path / "live-demo.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["live-demo", "--out", str(out_path), "--provider", "fake", "--stream"],
    )
    assert result.exit_code == 0, result.output
    source = read_artifact(out_path)

    replay_hashes: set[tuple[str | None, ...]] = set()
    for _ in range(50):
        replayed = replay_stub_run(
            source,
            config=ReplayConfig(seed=7, fixed_clock="2026-02-22T00:00:00Z"),
        )
        replay_hashes.add(tuple(step.hash for step in replayed.steps))

    assert len(replay_hashes) == 1


def test_live_demo_rejects_unknown_provider() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["live-demo", "--provider", "unknown"],
    )
    assert result.exit_code == 2
    assert "unsupported provider" in result.output
