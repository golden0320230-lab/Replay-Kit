from pathlib import Path

import replaykit

from replaypack.artifact import read_artifact, write_artifact
from replaypack.capture import build_demo_run
from replaypack.snapshot import (
    assert_snapshot_artifact,
    resolve_snapshot_baseline_path,
    update_snapshot_artifact,
)


def test_snapshot_workflow_update_and_assert_pass(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate_path)

    updated = update_snapshot_artifact(
        snapshot_name="demo-flow",
        candidate_path=candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert updated.status == "updated"
    assert Path(updated.baseline_path).exists()

    assertion = assert_snapshot_artifact(
        snapshot_name="demo-flow",
        candidate_path=candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert assertion.status == "pass"
    assert assertion.assertion is not None
    assert assertion.assertion.passed is True


def test_snapshot_workflow_detects_regression(tmp_path: Path) -> None:
    baseline_candidate_path = tmp_path / "candidate-baseline.rpk"
    write_artifact(build_demo_run(), baseline_candidate_path)
    update_snapshot_artifact(
        snapshot_name="demo-regression",
        candidate_path=baseline_candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )

    changed = build_demo_run()
    changed.steps[1].output = {"answer": "changed output"}
    changed_path = tmp_path / "candidate-changed.rpk"
    write_artifact(changed, changed_path)

    assertion = assert_snapshot_artifact(
        snapshot_name="demo-regression",
        candidate_path=changed_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert assertion.status == "fail"
    assert assertion.assertion is not None
    assert assertion.assertion.passed is False
    assert assertion.assertion.diff.first_divergence is not None


def test_snapshot_workflow_reports_missing_baseline(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate_path)

    result = assert_snapshot_artifact(
        snapshot_name="missing-baseline",
        candidate_path=candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert result.status == "error"
    assert "missing" in result.message


def test_snapshot_baseline_path_resolution_and_public_api(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate_path)

    resolved = resolve_snapshot_baseline_path("demo-name", tmp_path / "snapshots")
    assert resolved == (tmp_path / "snapshots" / "demo-name.rpk")

    updated = replaykit.snapshot_assert(
        "demo-name",
        candidate_path,
        snapshots_dir=tmp_path / "snapshots",
        update=True,
    )
    assert updated.status == "updated"

    asserted = replaykit.snapshot_assert(
        "demo-name",
        candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert asserted.status == "pass"
    assert asserted.assertion is not None
    assert asserted.assertion.passed is True


def test_snapshot_update_writes_readable_baseline(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate_path)

    result = update_snapshot_artifact(
        snapshot_name="demo-file",
        candidate_path=candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    baseline_run = read_artifact(result.baseline_path)
    assert baseline_run.id == "run-demo-001"
