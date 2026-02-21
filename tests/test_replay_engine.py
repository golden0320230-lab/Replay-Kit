from pathlib import Path

import pytest

from replaypack.artifact import read_artifact
from replaypack.replay import ReplayConfig, ReplayConfigError, replay_stub_run, write_replay_stub_artifact


def test_replay_stub_preserves_order_and_recorded_outputs() -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    replayed = replay_stub_run(source, config=ReplayConfig(seed=7, fixed_clock="2026-02-21T17:00:00Z"))

    assert replayed.timestamp == "2026-02-21T17:00:00.000000Z"
    assert replayed.environment_fingerprint["replay_mode"] == "stub"
    assert replayed.environment_fingerprint["replay_offline"] is True

    assert [step.type for step in replayed.steps] == [step.type for step in source.steps]
    assert [step.output for step in replayed.steps] == [step.output for step in source.steps]
    assert [step.id for step in replayed.steps] == [
        "step-000001",
        "step-000002",
        "step-000003",
        "step-000004",
        "step-000005",
        "step-000006",
    ]


def test_replay_same_seed_and_clock_is_byte_identical(tmp_path: Path) -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    config = ReplayConfig(seed=42, fixed_clock="2026-02-21T17:05:00Z")

    out_a = tmp_path / "a.rpk"
    out_b = tmp_path / "b.rpk"

    write_replay_stub_artifact(source, str(out_a), config=config)
    write_replay_stub_artifact(source, str(out_b), config=config)

    assert out_a.read_bytes() == out_b.read_bytes()


def test_replay_input_change_creates_artifact_divergence(tmp_path: Path) -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    changed = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    changed.steps[0].output = {"status": "changed"}

    config = ReplayConfig(seed=3, fixed_clock="2026-02-21T17:10:00Z")

    baseline_path = tmp_path / "baseline.rpk"
    changed_path = tmp_path / "changed.rpk"

    write_replay_stub_artifact(source, str(baseline_path), config=config)
    write_replay_stub_artifact(changed, str(changed_path), config=config)

    assert baseline_path.read_bytes() != changed_path.read_bytes()


def test_replay_requires_timezone_in_fixed_clock() -> None:
    with pytest.raises(ReplayConfigError, match="timezone"):
        ReplayConfig(seed=0, fixed_clock="2026-02-21T17:10:00")
