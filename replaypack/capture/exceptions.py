"""Capture subsystem exceptions."""


class CaptureError(Exception):
    """Base class for capture subsystem errors."""


class NoActiveRunError(CaptureError):
    """Raised when capture is requested without an active run context."""


class BoundaryPolicyError(CaptureError):
    """Raised when interception policy denies a boundary call."""
