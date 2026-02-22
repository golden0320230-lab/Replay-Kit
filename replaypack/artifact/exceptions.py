"""Artifact subsystem exceptions."""


class ArtifactError(Exception):
    """Base class for artifact errors."""


class ArtifactValidationError(ArtifactError):
    """Artifact failed schema or version validation."""


class ArtifactChecksumError(ArtifactError):
    """Artifact checksum mismatch."""


class ArtifactRedactionProfileError(ArtifactError):
    """Invalid bundle redaction profile."""


class ArtifactSignatureError(ArtifactError):
    """Artifact signature validation failed."""


class ArtifactSigningKeyError(ArtifactSignatureError):
    """Artifact signing key is missing or invalid."""
