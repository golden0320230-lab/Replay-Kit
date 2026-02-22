"""Artifact read/write utilities for `.rpk` files."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from replaypack.artifact.exceptions import ArtifactChecksumError, ArtifactSigningKeyError
from replaypack.artifact.schema import ArtifactValidationError
from replaypack.artifact.schema import DEFAULT_ARTIFACT_VERSION, validate_artifact
from replaypack.artifact.signing import sign_artifact_envelope
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
    sign: bool = False,
    signing_key: str | None = None,
    signing_key_id: str = "default",
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
    if sign:
        if not signing_key:
            raise ArtifactSigningKeyError(
                "Signing requested but no key provided. "
                "Set REPLAYKIT_SIGNING_KEY or pass --signing-key."
            )
        envelope = sign_artifact_envelope(
            envelope,
            signing_key=signing_key,
            key_id=signing_key_id,
        )
    return envelope


def write_artifact(
    run: Run,
    path: str | Path,
    *,
    version: str = DEFAULT_ARTIFACT_VERSION,
    metadata: dict[str, Any] | None = None,
    sign: bool = False,
    signing_key: str | None = None,
    signing_key_id: str = "default",
) -> dict[str, Any]:
    artifact = build_artifact_envelope(
        run,
        version=version,
        metadata=metadata,
        sign=sign,
        signing_key=signing_key,
        signing_key_id=signing_key_id,
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    canonical_artifact = canonicalize(artifact)
    target.write_text(
        json.dumps(canonical_artifact, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def read_artifact_envelope(path: str | Path) -> dict[str, Any]:
    """Read and validate artifact envelope with checksum verification."""
    target = Path(path)
    try:
        raw_text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ArtifactValidationError(
            f"Artifact is not valid UTF-8 text: {target}"
        ) from error

    try:
        artifact = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ArtifactValidationError(
            f"Artifact is not valid JSON: {target} ({error})"
        ) from error

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

    return artifact


def read_artifact(path: str | Path) -> Run:
    artifact = read_artifact_envelope(path)
    return Run.from_dict(artifact["payload"]["run"])
