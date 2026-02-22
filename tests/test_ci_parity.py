import json
from pathlib import Path

from replaypack.ci_parity import (
    DEFAULT_FIXED_CLOCK,
    DEFAULT_SEED,
    build_replay_parity_summary,
    compare_expected_parity,
    run_parity_check,
)


def test_build_replay_parity_summary_is_deterministic(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out_a = tmp_path / "a.rpk"
    out_b = tmp_path / "b.rpk"

    summary_a = build_replay_parity_summary(
        source_artifact=source,
        replay_artifact=out_a,
        seed=DEFAULT_SEED,
        fixed_clock=DEFAULT_FIXED_CLOCK,
    )
    summary_b = build_replay_parity_summary(
        source_artifact=source,
        replay_artifact=out_b,
        seed=DEFAULT_SEED,
        fixed_clock=DEFAULT_FIXED_CLOCK,
    )

    assert summary_a.artifact_checksum == summary_b.artifact_checksum
    assert summary_a.step_hash_digest == summary_b.step_hash_digest
    assert summary_a.replay_run_id == summary_b.replay_run_id
    assert summary_a.step_count == summary_b.step_count


def test_compare_expected_parity_reports_mismatch(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    summary = build_replay_parity_summary(
        source_artifact=source,
        replay_artifact=tmp_path / "out.rpk",
    )

    expected = summary.to_dict()
    expected["step_hash_digest"] = "sha256:deadbeef"
    mismatches = compare_expected_parity(summary, expected)

    assert mismatches
    assert "step_hash_digest" in mismatches[0]


def test_run_parity_check_passes_with_matching_expected(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    first_out_dir = tmp_path / "first"
    replay_artifact = first_out_dir / "parity-replay.rpk"
    first_summary = build_replay_parity_summary(
        source_artifact=source,
        replay_artifact=replay_artifact,
    )

    expected_path = tmp_path / "expected.json"
    expected = first_summary.to_dict()
    expected.pop("replay_artifact")
    expected.pop("source_artifact")
    expected_path.write_text(
        json.dumps(expected, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )

    payload = run_parity_check(
        source=source,
        out_dir=tmp_path / "second",
        expected_path=expected_path,
    )

    assert payload["status"] == "pass"
    assert payload["mismatch_count"] == 0
