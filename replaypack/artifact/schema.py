"""JSON schema and validation for `.rpk` artifacts."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from replaypack.artifact.exceptions import ArtifactValidationError
from replaypack.core.types import STEP_TYPES

SUPPORTED_MAJOR_VERSION = 1
DEFAULT_ARTIFACT_VERSION = "1.0"

ARTIFACT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ReplayKit Artifact",
    "type": "object",
    "required": ["version", "metadata", "payload", "checksum"],
    "additionalProperties": True,
    "properties": {
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+$",
            "description": "Major.minor artifact schema version",
        },
        "metadata": {
            "type": "object",
            "required": ["run_id", "created_at"],
            "additionalProperties": True,
            "properties": {
                "run_id": {"type": "string"},
                "created_at": {"type": "string"},
            },
        },
        "payload": {
            "type": "object",
            "required": ["run"],
            "additionalProperties": True,
            "properties": {
                "run": {
                    "type": "object",
                    "required": [
                        "id",
                        "timestamp",
                        "environment_fingerprint",
                        "runtime_versions",
                        "steps",
                    ],
                    "additionalProperties": True,
                    "properties": {
                        "id": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "environment_fingerprint": {"type": "object"},
                        "runtime_versions": {"type": "object"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "id",
                                    "type",
                                    "input",
                                    "output",
                                    "metadata",
                                    "hash",
                                ],
                                "additionalProperties": True,
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": list(STEP_TYPES),
                                    },
                                    "input": {},
                                    "output": {},
                                    "metadata": {"type": "object"},
                                    "hash": {
                                        "type": "string",
                                        "pattern": r"^sha256:[0-9a-f]{64}$",
                                    },
                                },
                            },
                        },
                    },
                }
            },
        },
        "checksum": {
            "type": "string",
            "pattern": r"^sha256:[0-9a-f]{64}$",
        },
    },
}


def validate_artifact(artifact: dict[str, Any]) -> None:
    """Validate artifact shape and supported version contract."""
    validator = Draft202012Validator(ARTIFACT_SCHEMA)
    errors = sorted(validator.iter_errors(artifact), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "$"
        raise ArtifactValidationError(f"Invalid artifact at {location}: {first.message}")

    version = artifact.get("version", "")
    major_str, _, _ = version.partition(".")
    try:
        major = int(major_str)
    except ValueError as exc:
        raise ArtifactValidationError(f"Invalid artifact version: {version}") from exc

    if major != SUPPORTED_MAJOR_VERSION:
        raise ArtifactValidationError(
            "Unsupported artifact major version: "
            f"{version}. Supported major: {SUPPORTED_MAJOR_VERSION}.x"
        )
