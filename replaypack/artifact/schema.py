"""JSON schema and validation for `.rpk` artifacts."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator

from replaypack.artifact.exceptions import ArtifactValidationError

SUPPORTED_MAJOR_VERSION = 1
DEFAULT_ARTIFACT_VERSION = "1.0"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

_VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)$")

# Fallback schema keeps runtime resilient if external schema files are unavailable.
_FALLBACK_ARTIFACT_SCHEMA_V1: dict[str, Any] = {
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
                                        "enum": [
                                            "prompt.render",
                                            "model.request",
                                            "model.response",
                                            "tool.request",
                                            "tool.response",
                                            "error.event",
                                            "output.final",
                                        ],
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


def parse_artifact_version(version: str) -> tuple[int, int]:
    """Parse major/minor artifact version."""
    match = _VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise ArtifactValidationError(f"Invalid artifact version: {version}")
    return int(match.group("major")), int(match.group("minor"))


def is_version_compatible(version: str) -> bool:
    """Return compatibility result for the current reader contract."""
    try:
        major, _ = parse_artifact_version(version)
    except ArtifactValidationError:
        return False
    return major == SUPPORTED_MAJOR_VERSION


def schema_path_for_version(version: str) -> Path:
    """Resolve schema file path for a given artifact version."""
    major, _minor = parse_artifact_version(version)
    return SCHEMA_DIR / f"rpk-{major}.0.schema.json"


@lru_cache(maxsize=8)
def load_artifact_schema(version: str) -> dict[str, Any]:
    """Load schema JSON for an artifact version (major-based resolution)."""
    schema_path = schema_path_for_version(version)
    if schema_path.exists():
        return json.loads(schema_path.read_text(encoding="utf-8"))
    if version.startswith("1."):
        return _FALLBACK_ARTIFACT_SCHEMA_V1
    raise ArtifactValidationError(f"Schema file not found for artifact version: {version}")


ARTIFACT_SCHEMA: dict[str, Any] = load_artifact_schema(DEFAULT_ARTIFACT_VERSION)


def validate_artifact(artifact: dict[str, Any]) -> None:
    """Validate artifact shape and supported version contract."""
    version = str(artifact.get("version", "")).strip()
    major, _minor = parse_artifact_version(version)

    if major != SUPPORTED_MAJOR_VERSION:
        raise ArtifactValidationError(
            "Unsupported artifact major version: "
            f"{version}. Supported major: {SUPPORTED_MAJOR_VERSION}.x"
        )

    validator = Draft202012Validator(load_artifact_schema(version))
    errors = sorted(validator.iter_errors(artifact), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "$"
        raise ArtifactValidationError(f"Invalid artifact at {location}: {first.message}")
