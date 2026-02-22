from pathlib import Path

import pytest

from replaypack.artifact import read_artifact
from replaypack.diff import diff_runs
from replaypack.replay import (
    HybridReplayPolicy,
    ReplayConfig,
    ReplayConfigError,
    replay_hybrid_run,
    replay_stub_run,
    write_replay_hybrid_artifact,
    write_replay_stub_artifact,
)


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


def test_replay_hybrid_reruns_selected_boundaries_and_marks_steps() -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    rerun = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    for step in rerun.steps:
        if step.type == "model.response":
            step.output = {"text": "changed-from-rerun"}

    policy = HybridReplayPolicy(rerun_step_types=("model.response",))
    hybrid = replay_hybrid_run(
        source,
        rerun,
        config=ReplayConfig(seed=12, fixed_clock="2026-02-21T17:30:00Z"),
        policy=policy,
    )

    assert hybrid.environment_fingerprint["replay_mode"] == "hybrid"
    assert hybrid.environment_fingerprint["rerun_from_run_id"] == rerun.id
    assert hybrid.runtime_versions["replay_rerun_step_types"] == "model.response"

    for source_step, replay_step in zip(source.steps, hybrid.steps, strict=True):
        if source_step.type == "model.response":
            assert replay_step.output == {"text": "changed-from-rerun"}
            assert replay_step.metadata["replay_strategy"] == "rerun"
            assert replay_step.metadata["rerun_from_run_id"] == rerun.id
        else:
            assert replay_step.output == source_step.output
            assert replay_step.metadata["replay_strategy"] == "stub"


def test_replay_hybrid_same_config_is_byte_identical(tmp_path: Path) -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    rerun = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    for step in rerun.steps:
        if step.type == "tool.response":
            step.output = {"status": "hybrid-rerun"}

    config = ReplayConfig(seed=77, fixed_clock="2026-02-21T17:35:00Z")
    policy = HybridReplayPolicy(rerun_step_types=("tool.response",))
    out_a = tmp_path / "hybrid-a.rpk"
    out_b = tmp_path / "hybrid-b.rpk"

    write_replay_hybrid_artifact(source, rerun, str(out_a), config=config, policy=policy)
    write_replay_hybrid_artifact(source, rerun, str(out_b), config=config, policy=policy)

    assert out_a.read_bytes() == out_b.read_bytes()


def test_replay_hybrid_requires_selector() -> None:
    with pytest.raises(ReplayConfigError, match="requires at least one selector"):
        HybridReplayPolicy()


def test_replay_hybrid_detects_alignment_mismatch() -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    rerun = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    rerun.steps.pop()

    with pytest.raises(ReplayConfigError, match="equal step count"):
        replay_hybrid_run(
            source,
            rerun,
            config=ReplayConfig(seed=2, fixed_clock="2026-02-21T17:40:00Z"),
            policy=HybridReplayPolicy(rerun_step_types=("model.response",)),
        )


def test_diff_detects_hybrid_divergence_from_stub(tmp_path: Path) -> None:
    source = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    rerun = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    for step in rerun.steps:
        if step.type == "model.response":
            step.output = {"text": "rerun-divergence"}

    config = ReplayConfig(seed=44, fixed_clock="2026-02-21T17:45:00Z")
    stub_path = tmp_path / "stub.rpk"
    hybrid_path = tmp_path / "hybrid.rpk"
    write_replay_stub_artifact(source, str(stub_path), config=config)
    write_replay_hybrid_artifact(
        source,
        rerun,
        str(hybrid_path),
        config=config,
        policy=HybridReplayPolicy(rerun_step_types=("model.response",)),
    )

    diff = diff_runs(read_artifact(stub_path), read_artifact(hybrid_path))
    assert diff.identical is False
    assert diff.first_divergence is not None
    assert diff.first_divergence.left_type == "model.response"
