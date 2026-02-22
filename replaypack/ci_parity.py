"""Cross-platform replay hash parity checks for CI workflows."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from replaypack.artifact import read_artifact, read_artifact_envelope
from replaypack.core.canonical import canonical_json
from replaypack.replay import ReplayConfig, write_replay_stub_artifact

DEFAULT_SOURCE = Path("examples/runs/m2_capture_boundaries.rpk")
DEFAULT_OUT_DIR = Path("runs/parity")
DEFAULT_EXPECTED = Path("ci/expected_hash_parity.json")
DEFAULT_SEED = 123
DEFAULT_FIXED_CLOCK = "2026-02-21T18:30:00Z"


@dataclass(slots=True, frozen=True)
class ParitySummary:
    source_artifact: str
    replay_artifact: str
    replay_run_id: str
    artifact_checksum: str
    step_hash_digest: str
    step_count: int
    seed: int
    fixed_clock: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_artifact": self.source_artifact,
            "replay_artifact": self.replay_artifact,
            "replay_run_id": self.replay_run_id,
            "artifact_checksum": self.artifact_checksum,
            "step_hash_digest": self.step_hash_digest,
            "step_count": self.step_count,
            "seed": self.seed,
            "fixed_clock": self.fixed_clock,
        }


def build_replay_parity_summary(
    source_artifact: Path,
    replay_artifact: Path,
    *,
    seed: int = DEFAULT_SEED,
    fixed_clock: str = DEFAULT_FIXED_CLOCK,
) -> ParitySummary:
    source_run = read_artifact(source_artifact)
    config = ReplayConfig(seed=seed, fixed_clock=fixed_clock)

    replay_artifact.parent.mkdir(parents=True, exist_ok=True)
    write_replay_stub_artifact(source_run, replay_artifact, config=config)

    envelope = read_artifact_envelope(replay_artifact)
    replay_run = envelope["payload"]["run"]
    step_hashes = [step["hash"] for step in replay_run["steps"]]
    step_hash_digest = _hash_string(canonical_json(step_hashes))

    return ParitySummary(
        source_artifact=str(source_artifact),
        replay_artifact=str(replay_artifact),
        replay_run_id=replay_run["id"],
        artifact_checksum=envelope["checksum"],
        step_hash_digest=f"sha256:{step_hash_digest}",
        step_count=len(step_hashes),
        seed=seed,
        fixed_clock=config.fixed_clock,
    )


def compare_expected_parity(summary: ParitySummary, expected: dict[str, Any]) -> list[str]:
    actual = summary.to_dict()
    mismatches: list[str] = []
    for key in sorted(expected.keys()):
        actual_value = actual.get(key)
        expected_value = expected.get(key)
        if actual_value != expected_value:
            mismatches.append(
                f"{key}: expected={expected_value!r} actual={actual_value!r}"
            )
    return mismatches


def run_parity_check(
    *,
    source: Path = DEFAULT_SOURCE,
    out_dir: Path = DEFAULT_OUT_DIR,
    expected_path: Path = DEFAULT_EXPECTED,
    seed: int = DEFAULT_SEED,
    fixed_clock: str = DEFAULT_FIXED_CLOCK,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    replay_artifact = out_dir / "parity-replay.rpk"
    summary_path = out_dir / "hash-parity-summary.json"

    summary = build_replay_parity_summary(
        source_artifact=source,
        replay_artifact=replay_artifact,
        seed=seed,
        fixed_clock=fixed_clock,
    )
    summary_path.write_text(
        json.dumps(summary.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    mismatches = compare_expected_parity(summary, expected)

    payload: dict[str, Any] = {
        "status": "pass" if not mismatches else "fail",
        "summary_path": str(summary_path),
        "expected_path": str(expected_path),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "summary": summary.to_dict(),
    }
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay artifact hash parity check for CI matrix.")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Source artifact path (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for parity artifacts (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=DEFAULT_EXPECTED,
        help=f"Expected parity JSON path (default: {DEFAULT_EXPECTED}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Replay seed (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--fixed-clock",
        type=str,
        default=DEFAULT_FIXED_CLOCK,
        help=f"Replay fixed clock (default: {DEFAULT_FIXED_CLOCK}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable payload.",
    )
    return parser.parse_args(argv)


def _hash_string(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_parity_check(
        source=args.source,
        out_dir=args.out_dir,
        expected_path=args.expected,
        seed=args.seed,
        fixed_clock=args.fixed_clock,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        status = payload["status"]
        summary_path = payload["summary_path"]
        mismatch_count = payload["mismatch_count"]
        print(
            f"hash parity {status}: summary={summary_path} mismatches={mismatch_count}"
        )
        for mismatch in payload["mismatches"]:
            print(f"- {mismatch}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
