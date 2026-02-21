"""Artifact subsystem exceptions."""


class ArtifactError(Exception):
    """Base class for artifact errors."""


class ArtifactValidationError(ArtifactError):
    """Artifact failed schema or version validation."""


class ArtifactChecksumError(ArtifactError):
    """Artifact checksum mismatch."""
