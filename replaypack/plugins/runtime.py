"""Runtime plugin activation helpers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
from typing import Iterator

from replaypack.plugins.base import PLUGIN_CONFIG_ENV_VAR
from replaypack.plugins.loader import load_plugin_manager_from_file
from replaypack.plugins.manager import PluginManager

_ACTIVE_PLUGIN_MANAGER: ContextVar[PluginManager | None] = ContextVar(
    "replaypack_active_plugin_manager",
    default=None,
)
_EMPTY_PLUGIN_MANAGER = PluginManager(plugins=())
_ENV_CACHE: tuple[str, PluginManager] | None = None


def get_active_plugin_manager() -> PluginManager:
    """Resolve active plugin manager from context override or env config."""
    manager = _ACTIVE_PLUGIN_MANAGER.get()
    if manager is not None:
        return manager

    config_path = os.getenv(PLUGIN_CONFIG_ENV_VAR, "").strip()
    if not config_path:
        return _EMPTY_PLUGIN_MANAGER

    global _ENV_CACHE
    if _ENV_CACHE is not None and _ENV_CACHE[0] == config_path:
        return _ENV_CACHE[1]

    loaded = load_plugin_manager_from_file(config_path)
    _ENV_CACHE = (config_path, loaded)
    return loaded


@contextmanager
def use_plugin_manager(manager: PluginManager) -> Iterator[PluginManager]:
    """Activate a plugin manager for current context."""
    token = _ACTIVE_PLUGIN_MANAGER.set(manager)
    try:
        yield manager
    finally:
        _ACTIVE_PLUGIN_MANAGER.reset(token)


@contextmanager
def use_plugins_from_config(path: str | Path) -> Iterator[PluginManager]:
    """Load plugins from config and activate in current context."""
    manager = load_plugin_manager_from_file(path)
    with use_plugin_manager(manager):
        yield manager


def reset_plugin_runtime_cache() -> None:
    """Clear cached env plugin manager (for tests)."""
    global _ENV_CACHE
    _ENV_CACHE = None
