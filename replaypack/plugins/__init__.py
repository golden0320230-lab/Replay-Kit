"""Plugin subsystem for ReplayKit lifecycle extensions."""

from replaypack.plugins.base import (
    PLUGIN_API_VERSION,
    PLUGIN_CONFIG_ENV_VAR,
    PLUGIN_CONFIG_VERSION,
    CaptureEndEvent,
    CaptureStartEvent,
    CaptureStepEvent,
    DiffEndEvent,
    DiffStartEvent,
    LifecyclePlugin,
    ReplayEndEvent,
    ReplayStartEvent,
)
from replaypack.plugins.exceptions import PluginConfigError, PluginError, PluginLoadError
from replaypack.plugins.fake_provider_adapter import FakeProviderAdapter
from replaypack.plugins.loader import load_plugin_manager_from_file
from replaypack.plugins.manager import PluginDiagnostic, PluginManager
from replaypack.plugins.provider_api import ProviderAdapter
from replaypack.plugins.reference import LifecycleTracePlugin
from replaypack.plugins.runtime import (
    get_active_plugin_manager,
    reset_plugin_runtime_cache,
    use_plugin_manager,
    use_plugins_from_config,
)

__all__ = [
    "PLUGIN_API_VERSION",
    "PLUGIN_CONFIG_VERSION",
    "PLUGIN_CONFIG_ENV_VAR",
    "PluginError",
    "PluginConfigError",
    "PluginLoadError",
    "ProviderAdapter",
    "FakeProviderAdapter",
    "CaptureStartEvent",
    "CaptureStepEvent",
    "CaptureEndEvent",
    "ReplayStartEvent",
    "ReplayEndEvent",
    "DiffStartEvent",
    "DiffEndEvent",
    "LifecyclePlugin",
    "PluginDiagnostic",
    "PluginManager",
    "LifecycleTracePlugin",
    "load_plugin_manager_from_file",
    "get_active_plugin_manager",
    "use_plugin_manager",
    "use_plugins_from_config",
    "reset_plugin_runtime_cache",
]
