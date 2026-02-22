import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import write_artifact
from replaypack.capture import build_demo_run
from replaypack.cli.app import app


def test_cli_snapshot_update_writes_baseline(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "snapshot",
            "demo-snapshot",
            "--candidate",
            str(candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--update",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "updated"
    assert payload["updated"] is True
    assert Path(payload["baseline_path"]).exists()


def test_cli_snapshot_assert_passes_after_update(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate)

    runner = CliRunner()
    update_result = runner.invoke(
        app,
        [
            "snapshot",
            "demo-pass",
            "--candidate",
            str(candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--update",
        ],
    )
    assert update_result.exit_code == 0

    assert_result = runner.invoke(
        app,
        [
            "snapshot",
            "demo-pass",
            "--candidate",
            str(candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--json",
        ],
    )
    assert assert_result.exit_code == 0
    payload = json.loads(assert_result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["assertion"]["status"] == "pass"


def test_cli_snapshot_assert_fails_for_regression(tmp_path: Path) -> None:
    baseline_candidate = tmp_path / "baseline.rpk"
    write_artifact(build_demo_run(), baseline_candidate)

    changed = build_demo_run()
    changed.steps[1].output = {"answer": "changed"}
    changed_candidate = tmp_path / "changed.rpk"
    write_artifact(changed, changed_candidate)

    runner = CliRunner()
    runner.invoke(
        app,
        [
            "snapshot",
            "demo-fail",
            "--candidate",
            str(baseline_candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--update",
        ],
        catch_exceptions=False,
    )

    result = runner.invoke(
        app,
        [
            "snapshot",
            "demo-fail",
            "--candidate",
            str(changed_candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["first_divergence"] is not None


def test_cli_snapshot_reports_missing_baseline(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.rpk"
    write_artifact(build_demo_run(), candidate)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "snapshot",
            "missing-snapshot",
            "--candidate",
            str(candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "missing" in payload["message"]


def test_cli_snapshot_requires_candidate_file(tmp_path: Path) -> None:
    baseline_candidate = tmp_path / "baseline.rpk"
    write_artifact(build_demo_run(), baseline_candidate)

    runner = CliRunner()
    runner.invoke(
        app,
        [
            "snapshot",
            "demo",
            "--candidate",
            str(baseline_candidate),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--update",
        ],
        catch_exceptions=False,
    )

    result = runner.invoke(
        app,
        [
            "snapshot",
            "demo",
            "--candidate",
            str(tmp_path / "missing.rpk"),
            "--snapshots-dir",
            str(tmp_path / "snapshots"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "snapshot failed" in payload["message"]
