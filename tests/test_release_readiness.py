from pathlib import Path
import re

import replaykit
from replaypack.artifact import read_artifact
from replaypack.diff import diff_runs
from replaypack.replay import ReplayConfig, write_replay_stub_artifact


def test_release_artifacts_exist_and_version_is_semver_like() -> None:
    assert Path("CHANGELOG.md").exists()
    assert Path("docs/RELEASES.md").exists()
    assert re.fullmatch(r"\d+\.\d+\.\d+", replaykit.__version__) is not None


def test_release_docs_reference_tag_and_upgrade_policy() -> None:
    text = Path("docs/RELEASES.md").read_text(encoding="utf-8").lower()
    assert "semantic versioning" in text
    assert "git tag -a vx.y.z" in text
    assert "docs/public_api.md" in text
    assert "release-notes-provider-capture-target-recording.md" in text


def test_readme_includes_ci_badge_and_stability_statement() -> None:
    text = Path("README.md").read_text(encoding="utf-8").lower()
    assert "actions/workflows/ci.yml/badge.svg" in text
    assert "compatibility & stability" in text
    assert "supported python versions" in text
    assert "platform guarantees" in text
    assert "semantic versioning policy" in text
    assert "backward compatibility guarantees" in text


def test_provider_capture_release_notes_template_exists() -> None:
    text = Path("docs/release-notes-provider-capture-target-recording.md").read_text(
        encoding="utf-8"
    ).lower()
    assert "provider capture" in text
    assert "target command recording" in text
    assert "replay remains offline deterministic" in text


def test_passive_mode_release_checklist_and_golden_artifact_replay(
    tmp_path: Path,
) -> None:
    checklist_path = Path("docs/PASSIVE_MODE_RELEASE_CHECKLIST.md")
    checklist_text = checklist_path.read_text(encoding="utf-8").lower()
    assert "cross-platform ci green" in checklist_text
    assert "no secret leakage" in checklist_text
    assert "deterministic replay parity" in checklist_text
    assert "examples/runs/passive_listener_golden_path.rpk" in checklist_text

    artifact_path = Path("examples/runs/passive_listener_golden_path.rpk")
    assert artifact_path.exists()
    source_run = read_artifact(artifact_path)
    assert source_run.source == "listener"
    assert source_run.capture_mode == "passive"
    assert len(source_run.steps) >= 2

    replay_a = tmp_path / "passive-golden-replay-a.rpk"
    replay_b = tmp_path / "passive-golden-replay-b.rpk"
    config = ReplayConfig(seed=23, fixed_clock="2026-02-23T00:00:00Z")
    write_replay_stub_artifact(source_run, str(replay_a), config=config)
    write_replay_stub_artifact(source_run, str(replay_b), config=config)

    assert replay_a.read_bytes() == replay_b.read_bytes()
    diff = diff_runs(read_artifact(replay_a), read_artifact(replay_b))
    assert diff.identical is True
    assert diff.first_divergence is None
