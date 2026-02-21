"""Replay subsystem exceptions."""


class ReplayError(Exception):
    """Base class for replay errors."""


class ReplayConfigError(ReplayError):
    """Invalid replay configuration."""
