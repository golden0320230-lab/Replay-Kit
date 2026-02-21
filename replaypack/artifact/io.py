"""Artifact read/write utilities for `.rpk` files."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from replaypack.artifact.exceptions import ArtifactChecksumError
from replaypack.artifact.schema import DEFAULT_ARTIFACT_VERSION, validate_artifact
from replaypack.core.canonical import canonical_json, canonicalize
from replaypack.core.models import Run


def compute_artifact_checksum(artifact_without_checksum: dict[str, Any]) -> str:
    payload = canonical_json(artifact_without_checksum)
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_artifact_envelope(
    run: Run,
    *,
    version: str = DEFAULT_ARTIFACT_VERSION,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_hashed = run.with_hashed_steps()

    envelope: dict[str, Any] = {
        "version": version,
        "metadata": {
            "run_id": run.id,
            "created_at": run.timestamp,
            **(metadata or {}),
        },
        "payload": {
            "run": run_hashed.to_dict(),
        },
    }

    envelope["checksum"] = compute_artifact_checksum(envelope)
    validate_artifact(envelope)
    return envelope


def write_artifact(
    run: Run,
    path: str | Path,
    *,
    version: str = DEFAULT_ARTIFACT_VERSION,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = build_artifact_envelope(run, version=version, metadata=metadata)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    canonical_artifact = canonicalize(artifact)
    target.write_text(
        json.dumps(canonical_artifact, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def read_artifact(path: str | Path) -> Run:
    target = Path(path)
    artifact = json.loads(target.read_text(encoding="utf-8"))
    validate_artifact(artifact)

    checksum_actual = artifact.get("checksum")
    checksum_expected = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )

    if checksum_actual != checksum_expected:
        raise ArtifactChecksumError(
            "Artifact checksum mismatch: "
            f"expected {checksum_expected}, got {checksum_actual}"
        )

    return Run.from_dict(artifact["payload"]["run"])
