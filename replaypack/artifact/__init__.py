"""Artifact subsystem for ReplayKit."""

from replaypack.artifact.bundle import (
    NONE_REDACTION_POLICY,
    redact_run_for_bundle,
    resolve_redaction_policy,
    write_bundle_artifact,
)
from replaypack.artifact.exceptions import (
    ArtifactChecksumError,
    ArtifactError,
    ArtifactMigrationError,
    ArtifactRedactionProfileError,
    ArtifactSignatureError,
    ArtifactSigningKeyError,
    ArtifactValidationError,
)
from replaypack.artifact.io import (
    build_artifact_envelope,
    compute_artifact_checksum,
    read_artifact,
    read_artifact_envelope,
    write_artifact,
)
from replaypack.artifact.migration import (
    ArtifactMigrationResult,
    LEGACY_SOURCE_VERSION,
    SUPPORTED_SOURCE_VERSIONS,
    migrate_artifact_envelope,
    migrate_artifact_file,
)
from replaypack.artifact.schema import (
    ARTIFACT_SCHEMA,
    DEFAULT_ARTIFACT_VERSION,
    SCHEMA_DIR,
    is_version_compatible,
    load_artifact_schema,
    parse_artifact_version,
    schema_path_for_version,
    validate_artifact,
)
from replaypack.artifact.signing import (
    SIGNATURE_ALGORITHM,
    SIGNING_KEY_ENV_VAR,
    SIGNING_KEY_ID_ENV_VAR,
    SignatureVerificationResult,
    compute_artifact_hmac,
    sign_artifact_envelope,
    verify_artifact_signature,
)

__all__ = [
    "ARTIFACT_SCHEMA",
    "DEFAULT_ARTIFACT_VERSION",
    "SCHEMA_DIR",
    "parse_artifact_version",
    "is_version_compatible",
    "schema_path_for_version",
    "load_artifact_schema",
    "ArtifactError",
    "ArtifactValidationError",
    "ArtifactChecksumError",
    "ArtifactMigrationError",
    "ArtifactRedactionProfileError",
    "ArtifactSignatureError",
    "ArtifactSigningKeyError",
    "NONE_REDACTION_POLICY",
    "resolve_redaction_policy",
    "redact_run_for_bundle",
    "write_bundle_artifact",
    "build_artifact_envelope",
    "compute_artifact_checksum",
    "validate_artifact",
    "write_artifact",
    "read_artifact",
    "read_artifact_envelope",
    "LEGACY_SOURCE_VERSION",
    "SUPPORTED_SOURCE_VERSIONS",
    "ArtifactMigrationResult",
    "migrate_artifact_envelope",
    "migrate_artifact_file",
    "SIGNATURE_ALGORITHM",
    "SIGNING_KEY_ENV_VAR",
    "SIGNING_KEY_ID_ENV_VAR",
    "SignatureVerificationResult",
    "compute_artifact_hmac",
    "sign_artifact_envelope",
    "verify_artifact_signature",
]
