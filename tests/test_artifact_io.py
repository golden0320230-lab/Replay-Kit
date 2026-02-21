import json
from pathlib import Path

import pytest

from replaypack.artifact import (
    ArtifactChecksumError,
    ArtifactValidationError,
    build_artifact_envelope,
    compute_artifact_checksum,
    read_artifact,
    validate_artifact,
    write_artifact,
)
from replaypack.core.canonical import canonicalize
from replaypack.core.models import Run, Step


@pytest.fixture()
def sample_run() -> Run:
    return Run(
        id="run-001",
        timestamp="2026-02-21T14:00:00Z",
        environment_fingerprint={
            "os": "macOS",
            "cwd": "C:\\Users\\alice\\replaykit",
        },
        runtime_versions={
            "python": "3.12.1",
            "replaykit": "0.1.0",
        },
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "Summarize this"},
                output={"status": "sent"},
                metadata={"provider": "openai", "duration_ms": 3},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "abc"},
                output={"content": "Summary text"},
                metadata={"provider": "openai", "latency_ms": 8},
            ),
        ],
    )


def test_round_trip_write_and_read(sample_run: Run, tmp_path: Path) -> None:
    artifact_path = tmp_path / "sample.rpk"

    envelope = write_artifact(sample_run, artifact_path)
    loaded = read_artifact(artifact_path)

    validate_artifact(envelope)
    expected = canonicalize(sample_run.with_hashed_steps().to_dict())
    assert loaded.to_dict() == expected


def test_invalid_artifact_missing_required_field_fails(sample_run: Run) -> None:
    artifact = build_artifact_envelope(sample_run)
    del artifact["payload"]["run"]["id"]

    with pytest.raises(ArtifactValidationError, match="payload.run"):
        validate_artifact(artifact)


def test_checksum_mismatch_fails(sample_run: Run, tmp_path: Path) -> None:
    artifact_path = tmp_path / "sample.rpk"
    write_artifact(sample_run, artifact_path)

    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    raw["payload"]["run"]["steps"][0]["output"]["status"] = "tampered"
    artifact_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        read_artifact(artifact_path)


def test_unsupported_major_version_fails(sample_run: Run) -> None:
    artifact = build_artifact_envelope(sample_run)
    artifact["version"] = "2.0"
    artifact["checksum"] = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )

    with pytest.raises(ArtifactValidationError, match="Unsupported artifact major version"):
        validate_artifact(artifact)


def test_example_fixture_is_valid() -> None:
    fixture_path = Path("examples/runs/minimal_v1.rpk")
    run = read_artifact(fixture_path)

    assert run.id == "run-example-001"
    assert len(run.steps) == 2


def test_capture_fixture_is_valid() -> None:
    fixture_path = Path("examples/runs/m2_capture_boundaries.rpk")
    run = read_artifact(fixture_path)

    assert run.id == "run-m2-example-001"
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "tool.request",
        "tool.response",
        "tool.request",
        "tool.response",
    ]


def test_replay_fixture_is_valid() -> None:
    fixture_path = Path("examples/runs/m3_replay_stub_from_m2.rpk")
    run = read_artifact(fixture_path)

    assert run.environment_fingerprint["replay_mode"] == "stub"
    assert run.environment_fingerprint["replay_offline"] is True
    assert run.runtime_versions["replay_seed"] == "21"
    assert len(run.steps) == 6


def test_diff_fixture_is_valid() -> None:
    fixture_path = Path("examples/runs/m4_diverged_from_m2.rpk")
    run = read_artifact(fixture_path)

    assert run.id == "run-m2-example-001"
    assert run.steps[2].input["args"] == ["forecast"]
    assert run.steps[2].metadata["tool"] == "search-v2"
