import json
from pathlib import Path

import pytest

from replaypack.artifact import (
    ArtifactMigrationError,
    compute_artifact_checksum,
    migrate_artifact_envelope,
    migrate_artifact_file,
    read_artifact,
)
from replaypack.core.hashing import compute_step_hash


def _legacy_v0_9_artifact(*, valid_hash: bool = True) -> dict:
    request_payload = {"query": "weather sf"}
    response_payload = {"status": "ok"}
    metadata = {"tool": "search"}
    step_hash = compute_step_hash("tool.request", request_payload, response_payload, metadata)
    if not valid_hash:
        step_hash = "sha256:" + ("0" * 64)

    artifact = {
        "version": "0.9",
        "metadata": {
            "run_id": "run-legacy-001",
            "created_at": "2026-02-22T19:00:00Z",
            "owner": "migration-test",
        },
        "payload": {
            "run": {
                "id": "run-legacy-001",
                "timestamp": "2026-02-22T19:00:00Z",
                "env_fingerprint": {"os": "macOS"},
                "runtime": {"python": "3.11.9", "replaykit": "0.0.9"},
                "steps": [
                    {
                        "id": "step-000001",
                        "type": "tool.request",
                        "request": request_payload,
                        "response": response_payload,
                        "metadata": metadata,
                        "step_hash": step_hash,
                    }
                ],
            }
        },
    }
    artifact["checksum"] = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )
    return artifact


def _unsupported_artifact(version: str = "3.0") -> dict:
    artifact = {
        "version": version,
        "metadata": {"run_id": "run-unsupported", "created_at": "2026-02-22T19:01:00Z"},
        "payload": {
            "run": {
                "id": "run-unsupported",
                "timestamp": "2026-02-22T19:01:00Z",
                "environment_fingerprint": {},
                "runtime_versions": {},
                "steps": [],
            }
        },
    }
    artifact["checksum"] = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )
    return artifact


def test_migrate_legacy_v0_9_to_current(tmp_path: Path) -> None:
    source = tmp_path / "legacy-0.9.rpk"
    out = tmp_path / "migrated.rpk"
    source.write_text(
        json.dumps(_legacy_v0_9_artifact(valid_hash=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = migrate_artifact_file(source, out)
    migrated_raw = json.loads(out.read_text(encoding="utf-8"))
    migrated_run = read_artifact(out)

    assert migrated_raw["version"] == "1.0"
    assert migrated_raw["metadata"]["migration_source_version"] == "0.9"
    assert migrated_raw["metadata"]["migration_target_version"] == "1.0"
    assert migrated_raw["metadata"]["migration_status"] == "migrated"
    assert summary.preserved_step_hashes == 1
    assert summary.recomputed_step_hashes == 0
    assert migrated_run.environment_fingerprint["os"] == "macOS"
    assert migrated_run.runtime_versions["python"] == "3.11.9"
    assert migrated_run.steps[0].input["query"] == "weather sf"
    assert migrated_run.steps[0].output["status"] == "ok"


def test_migrate_recomputes_invalid_legacy_step_hash() -> None:
    migrated, summary = migrate_artifact_envelope(_legacy_v0_9_artifact(valid_hash=False))
    step = migrated["payload"]["run"]["steps"][0]

    assert summary.preserved_step_hashes == 0
    assert summary.recomputed_step_hashes == 1
    assert step["hash"] == compute_step_hash(
        "tool.request",
        {"query": "weather sf"},
        {"status": "ok"},
        {"tool": "search"},
    )


def test_migrate_unsupported_source_version_fails() -> None:
    with pytest.raises(ArtifactMigrationError, match="unsupported source artifact version"):
        migrate_artifact_envelope(_unsupported_artifact())
