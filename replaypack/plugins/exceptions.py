"""Plugin subsystem exceptions."""


class PluginError(Exception):
    """Base class for plugin subsystem errors."""


class PluginConfigError(PluginError):
    """Raised when plugin config is malformed."""


class PluginLoadError(PluginError):
    """Raised when plugin entrypoint loading/instantiation fails."""
