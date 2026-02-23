import json
from pathlib import Path

import pytest

from replaypack.artifact import (
    SCHEMA_DIR,
    build_artifact_envelope,
    compute_artifact_checksum,
    is_version_compatible,
    load_artifact_schema,
    parse_artifact_version,
    read_artifact,
    schema_path_for_version,
    validate_artifact,
)
from replaypack.artifact.exceptions import ArtifactValidationError
from replaypack.core.models import Run, Step


def _sample_run() -> Run:
    return Run(
        id="run-schema-contract-001",
        timestamp="2026-02-22T15:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.0", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "req-1"},
                output={"content": "hi"},
                metadata={"provider": "openai"},
            ),
        ],
    )


def test_schema_file_is_published_under_stable_path() -> None:
    path = schema_path_for_version("1.0")
    assert path == SCHEMA_DIR / "rpk-1.0.schema.json"
    assert path.exists()

    schema_from_loader = load_artifact_schema("1.0")
    schema_from_disk = json.loads(path.read_text(encoding="utf-8"))
    assert schema_from_loader == schema_from_disk


def test_reader_accepts_minor_versions_within_same_major() -> None:
    run = _sample_run()
    artifact = build_artifact_envelope(run, version="1.7")

    validate_artifact(artifact)
    assert is_version_compatible("1.0") is True
    assert is_version_compatible("1.7") is True
    assert parse_artifact_version("1.7") == (1, 7)


def test_unknown_fields_are_forward_compatible(tmp_path: Path) -> None:
    run = _sample_run()
    artifact = build_artifact_envelope(run, version="1.4")

    artifact["future_root"] = {"flag": True}
    artifact["metadata"]["future_meta"] = {"owner": "team-a"}
    artifact["payload"]["future_payload"] = {"notes": ["x", "y"]}
    artifact["payload"]["run"]["future_run_field"] = {"experiment": 42}
    artifact["payload"]["run"]["steps"][0]["future_step_field"] = "allowed"
    artifact["checksum"] = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )

    validate_artifact(artifact)

    path = tmp_path / "forward-compatible.rpk"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loaded_run = read_artifact(path)
    assert loaded_run.id == run.id
    assert len(loaded_run.steps) == len(run.steps)


def test_listener_run_metadata_fields_validate_and_round_trip(tmp_path: Path) -> None:
    run = _sample_run()
    run.source = "listener"
    run.capture_mode = "passive"
    run.listener_session_id = "listener-session-001"
    run.listener_process = {"pid": 1001, "executable": "/usr/bin/python3"}
    run.listener_bind = {"host": "127.0.0.1", "port": 9000}

    artifact = build_artifact_envelope(run, version="1.0")
    validate_artifact(artifact)

    path = tmp_path / "listener-schema.rpk"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loaded = read_artifact(path)
    assert loaded.source == "listener"
    assert loaded.capture_mode == "passive"
    assert loaded.listener_session_id == "listener-session-001"
    assert loaded.listener_process == {"pid": 1001, "executable": "/usr/bin/python3"}
    assert loaded.listener_bind == {"host": "127.0.0.1", "port": 9000}


def test_major_version_mismatch_is_not_compatible() -> None:
    assert is_version_compatible("2.0") is False
    with pytest.raises(ArtifactValidationError, match="Unsupported artifact major version"):
        validate_artifact(
            {
                "version": "2.0",
                "metadata": {"run_id": "r", "created_at": "2026-02-22T15:00:00Z"},
                "payload": {"run": {"id": "r", "timestamp": "2026-02-22T15:00:00Z", "environment_fingerprint": {}, "runtime_versions": {}, "steps": []}},
                "checksum": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            }
        )
