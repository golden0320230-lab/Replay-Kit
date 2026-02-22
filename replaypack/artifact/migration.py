"""Artifact migration utilities for schema upgrade paths."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from replaypack.artifact.exceptions import (
    ArtifactChecksumError,
    ArtifactMigrationError,
)
from replaypack.artifact.io import (
    build_artifact_envelope,
    compute_artifact_checksum,
)
from replaypack.artifact.schema import DEFAULT_ARTIFACT_VERSION, parse_artifact_version, validate_artifact
from replaypack.core.canonical import canonicalize
from replaypack.core.models import Run, Step

MigrationStatus = Literal["migrated", "already_current"]

LEGACY_SOURCE_VERSION = "0.9"
SUPPORTED_SOURCE_VERSIONS = (LEGACY_SOURCE_VERSION, DEFAULT_ARTIFACT_VERSION)


@dataclass(frozen=True, slots=True)
class ArtifactMigrationResult:
    source_version: str
    target_version: str
    source_run_id: str
    migrated_run_id: str
    total_steps: int
    preserved_step_hashes: int
    recomputed_step_hashes: int
    status: MigrationStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_version": self.source_version,
            "target_version": self.target_version,
            "source_run_id": self.source_run_id,
            "migrated_run_id": self.migrated_run_id,
            "total_steps": self.total_steps,
            "preserved_step_hashes": self.preserved_step_hashes,
            "recomputed_step_hashes": self.recomputed_step_hashes,
            "migration_status": self.status,
        }


def migrate_artifact_envelope(
    source_envelope: dict[str, Any],
    *,
    target_version: str = DEFAULT_ARTIFACT_VERSION,
) -> tuple[dict[str, Any], ArtifactMigrationResult]:
    """Migrate an artifact envelope into the requested target schema version."""
    source_version = _version_from_envelope(source_envelope)
    source_run, stats = _run_from_source_envelope(source_envelope, source_version=source_version)

    if source_version == target_version:
        status: MigrationStatus = "already_current"
    else:
        status = "migrated"

    metadata = _metadata_extras(source_envelope)
    metadata["migration_source_version"] = source_version
    metadata["migration_target_version"] = target_version
    metadata["migration_status"] = status
    metadata["migration_preserved_step_hashes"] = stats["preserved"]
    metadata["migration_recomputed_step_hashes"] = stats["recomputed"]

    migrated = build_artifact_envelope(
        source_run,
        version=target_version,
        metadata=metadata,
    )

    summary = ArtifactMigrationResult(
        source_version=source_version,
        target_version=target_version,
        source_run_id=_source_run_id(source_envelope),
        migrated_run_id=migrated["payload"]["run"]["id"],
        total_steps=len(migrated["payload"]["run"]["steps"]),
        preserved_step_hashes=stats["preserved"],
        recomputed_step_hashes=stats["recomputed"],
        status=status,
    )
    return migrated, summary


def migrate_artifact_file(
    source_path: str | Path,
    out_path: str | Path,
    *,
    target_version: str = DEFAULT_ARTIFACT_VERSION,
) -> ArtifactMigrationResult:
    """Migrate an artifact file to the target schema and persist output."""
    raw = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ArtifactMigrationError("artifact file must contain a JSON object")

    migrated, summary = migrate_artifact_envelope(
        raw,
        target_version=target_version,
    )
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(canonicalize(migrated), indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _version_from_envelope(source_envelope: dict[str, Any]) -> str:
    source_version = str(source_envelope.get("version", "")).strip()
    if not source_version:
        raise ArtifactMigrationError("source artifact is missing version")
    return source_version


def _run_from_source_envelope(
    source_envelope: dict[str, Any],
    *,
    source_version: str,
) -> tuple[Run, dict[str, int]]:
    if source_version == LEGACY_SOURCE_VERSION:
        _validate_legacy_v0_9_envelope(source_envelope)
        return _run_from_legacy_v0_9(source_envelope)

    major, _minor = parse_artifact_version(source_version)
    if major != 1:
        raise ArtifactMigrationError(
            "unsupported source artifact version "
            f"'{source_version}'. Supported versions: {', '.join(SUPPORTED_SOURCE_VERSIONS)}"
        )
    _validate_supported_source_envelope(source_envelope)
    return _run_from_v1_envelope(source_envelope)


def _validate_supported_source_envelope(source_envelope: dict[str, Any]) -> None:
    validate_artifact(source_envelope)
    _verify_checksum(source_envelope)


def _validate_legacy_v0_9_envelope(source_envelope: dict[str, Any]) -> None:
    required_root = ("metadata", "payload", "checksum")
    missing_root = [key for key in required_root if key not in source_envelope]
    if missing_root:
        raise ArtifactMigrationError(
            "legacy artifact missing required root key(s): " + ", ".join(missing_root)
        )

    payload = source_envelope.get("payload")
    if not isinstance(payload, dict) or "run" not in payload or not isinstance(payload["run"], dict):
        raise ArtifactMigrationError("legacy artifact payload.run must be an object")

    run_raw = payload["run"]
    for key in ("id", "timestamp", "steps"):
        if key not in run_raw:
            raise ArtifactMigrationError(f"legacy artifact payload.run missing key: {key}")
    if not isinstance(run_raw.get("steps"), list):
        raise ArtifactMigrationError("legacy artifact payload.run.steps must be an array")

    _verify_checksum(source_envelope)


def _verify_checksum(source_envelope: dict[str, Any]) -> None:
    expected = compute_artifact_checksum(
        {
            "version": source_envelope["version"],
            "metadata": source_envelope["metadata"],
            "payload": source_envelope["payload"],
        }
    )
    actual = source_envelope.get("checksum")
    if actual != expected:
        raise ArtifactChecksumError(
            "Artifact checksum mismatch: "
            f"expected {expected}, got {actual}"
        )


def _run_from_v1_envelope(source_envelope: dict[str, Any]) -> tuple[Run, dict[str, int]]:
    run_raw = source_envelope["payload"]["run"]
    steps: list[Step] = []
    preserved = 0
    recomputed = 0

    for step_raw in run_raw.get("steps", []):
        if not isinstance(step_raw, dict):
            raise ArtifactMigrationError("step entries must be objects")
        migrated_step = Step(
            id=str(step_raw["id"]),
            type=str(step_raw["type"]),
            input=step_raw.get("input"),
            output=step_raw.get("output"),
            metadata=dict(step_raw.get("metadata", {})),
        ).with_hash()
        source_hash = _normalize_optional_hash(step_raw.get("hash"))
        if source_hash is not None and source_hash == migrated_step.hash:
            preserved += 1
        else:
            recomputed += 1
        steps.append(migrated_step)

    run = Run(
        id=str(run_raw["id"]),
        timestamp=str(run_raw["timestamp"]),
        environment_fingerprint=dict(run_raw.get("environment_fingerprint", {})),
        runtime_versions=dict(run_raw.get("runtime_versions", {})),
        steps=steps,
    )
    return run, {"preserved": preserved, "recomputed": recomputed}


def _run_from_legacy_v0_9(source_envelope: dict[str, Any]) -> tuple[Run, dict[str, int]]:
    run_raw = source_envelope["payload"]["run"]
    steps: list[Step] = []
    preserved = 0
    recomputed = 0

    for step_raw in run_raw.get("steps", []):
        if not isinstance(step_raw, dict):
            raise ArtifactMigrationError("legacy step entries must be objects")
        migrated_step = Step(
            id=str(step_raw["id"]),
            type=str(step_raw["type"]),
            input=step_raw.get("input", step_raw.get("request")),
            output=step_raw.get("output", step_raw.get("response")),
            metadata=dict(step_raw.get("metadata", {})),
        ).with_hash()
        source_hash = _normalize_optional_hash(step_raw.get("step_hash", step_raw.get("hash")))
        if source_hash is not None and source_hash == migrated_step.hash:
            preserved += 1
        else:
            recomputed += 1
        steps.append(migrated_step)

    run = Run(
        id=str(run_raw["id"]),
        timestamp=str(run_raw["timestamp"]),
        environment_fingerprint=dict(run_raw.get("env_fingerprint", {})),
        runtime_versions=dict(run_raw.get("runtime", {})),
        steps=steps,
    )
    return run, {"preserved": preserved, "recomputed": recomputed}


def _metadata_extras(source_envelope: dict[str, Any]) -> dict[str, Any]:
    metadata_raw = source_envelope.get("metadata", {})
    if not isinstance(metadata_raw, dict):
        raise ArtifactMigrationError("artifact metadata must be an object")
    return {
        key: value
        for key, value in metadata_raw.items()
        if key not in {"run_id", "created_at"}
    }


def _source_run_id(source_envelope: dict[str, Any]) -> str:
    run_raw = source_envelope.get("payload", {}).get("run", {})
    if isinstance(run_raw, dict) and "id" in run_raw:
        return str(run_raw["id"])
    metadata = source_envelope.get("metadata", {})
    if isinstance(metadata, dict) and "run_id" in metadata:
        return str(metadata["run_id"])
    return "<unknown>"


def _normalize_optional_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
