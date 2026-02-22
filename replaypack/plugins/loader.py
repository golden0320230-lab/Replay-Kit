"""Versioned plugin configuration loader."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

from replaypack.plugins.base import PLUGIN_API_VERSION, PLUGIN_CONFIG_VERSION
from replaypack.plugins.exceptions import PluginConfigError, PluginLoadError
from replaypack.plugins.manager import PluginManager


def load_plugin_manager_from_file(path: str | Path) -> PluginManager:
    """Load a plugin manager from JSON config."""
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as error:
        raise PluginConfigError(f"Invalid plugin config JSON ({config_path}): {error}") from error

    if not isinstance(raw, dict):
        raise PluginConfigError(f"Plugin config must be a JSON object ({config_path}).")

    version = raw.get("config_version")
    if version != PLUGIN_CONFIG_VERSION:
        raise PluginConfigError(
            "Unsupported plugin config version "
            f"{version!r}; expected {PLUGIN_CONFIG_VERSION}."
        )

    plugins_payload = raw.get("plugins")
    if not isinstance(plugins_payload, list):
        raise PluginConfigError("Plugin config key 'plugins' must be a JSON array.")

    plugins: list[object] = []
    for index, payload in enumerate(plugins_payload, start=1):
        plugin = _load_plugin_payload(payload, index=index)
        if plugin is not None:
            plugins.append(plugin)

    return PluginManager(plugins=tuple(plugins))


def _load_plugin_payload(payload: Any, *, index: int) -> object | None:
    if not isinstance(payload, dict):
        raise PluginConfigError(f"Plugin entry #{index} must be a JSON object.")

    supported_keys = {"entrypoint", "options", "enabled"}
    unknown = sorted(set(payload.keys()) - supported_keys)
    if unknown:
        raise PluginConfigError(
            f"Plugin entry #{index} contains unsupported keys: {', '.join(unknown)}"
        )

    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise PluginConfigError(f"Plugin entry #{index} key 'enabled' must be boolean.")
    if not enabled:
        return None

    entrypoint = payload.get("entrypoint")
    if not isinstance(entrypoint, str) or ":" not in entrypoint:
        raise PluginConfigError(
            f"Plugin entry #{index} key 'entrypoint' must be 'module:attribute'."
        )

    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise PluginConfigError(f"Plugin entry #{index} key 'options' must be a JSON object.")

    target = _import_entrypoint(entrypoint, index=index)
    plugin = _instantiate_plugin(target, entrypoint=entrypoint, options=options, index=index)
    _validate_api_version(plugin, entrypoint=entrypoint, index=index)
    return plugin


def _import_entrypoint(entrypoint: str, *, index: int) -> object:
    module_name, _, attribute = entrypoint.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        raise PluginLoadError(
            f"Plugin entry #{index} failed to import module '{module_name}': {error}"
        ) from error

    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise PluginLoadError(
            f"Plugin entry #{index} could not find attribute '{attribute}' in '{module_name}'."
        ) from error


def _instantiate_plugin(
    target: object,
    *,
    entrypoint: str,
    options: dict[str, Any],
    index: int,
) -> object:
    if inspect.isclass(target) or callable(target):
        try:
            return target(**options)
        except Exception as error:
            raise PluginLoadError(
                f"Plugin entry #{index} failed to instantiate '{entrypoint}' "
                f"with options {sorted(options.keys())}: {error}"
            ) from error

    if options:
        raise PluginLoadError(
            f"Plugin entry #{index} uses non-callable '{entrypoint}' and cannot accept options."
        )
    return target


def _validate_api_version(plugin: object, *, entrypoint: str, index: int) -> None:
    version = str(getattr(plugin, "api_version", PLUGIN_API_VERSION))
    if not _is_supported_api_version(version):
        raise PluginLoadError(
            f"Plugin entry #{index} '{entrypoint}' declares unsupported api_version "
            f"{version!r}; supported major version is {PLUGIN_API_VERSION.split('.', 1)[0]}."
        )


def _is_supported_api_version(version: str) -> bool:
    expected_major = PLUGIN_API_VERSION.split(".", 1)[0]
    return version.split(".", 1)[0] == expected_major
