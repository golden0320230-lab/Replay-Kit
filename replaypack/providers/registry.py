"""Provider adapter registry and plugin hooks."""

from __future__ import annotations

import importlib
from typing import Any, Callable

from replaypack.providers.base import ProviderAdapter

ProviderFactory = Callable[[], ProviderAdapter]
_PROVIDER_REGISTRY: dict[str, ProviderFactory] = {}


class ProviderRegistryError(ValueError):
    """Raised when provider adapter registration fails."""


def register_provider_adapter(
    key: str,
    factory: ProviderFactory,
    *,
    overwrite: bool = False,
) -> None:
    normalized_key = key.strip().lower()
    if not normalized_key:
        raise ProviderRegistryError("Provider key cannot be empty.")
    if not overwrite and normalized_key in _PROVIDER_REGISTRY:
        raise ProviderRegistryError(f"Provider '{normalized_key}' is already registered.")
    _PROVIDER_REGISTRY[normalized_key] = factory


def register_provider_adapter_class(
    key: str,
    adapter_cls: type[ProviderAdapter],
    *,
    overwrite: bool = False,
) -> None:
    register_provider_adapter(key, adapter_cls, overwrite=overwrite)


def register_provider_adapter_entrypoint(
    key: str,
    entrypoint: str,
    *,
    overwrite: bool = False,
) -> None:
    module_name, separator, attr = entrypoint.partition(":")
    if not separator:
        raise ProviderRegistryError(
            f"Invalid provider adapter entrypoint '{entrypoint}'. Expected module:attribute."
        )
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    if isinstance(target, type):
        adapter_cls = target
    elif callable(target):
        adapter = target()
        adapter_cls = type(adapter)
    else:
        raise ProviderRegistryError(
            f"Provider adapter entrypoint '{entrypoint}' is not callable."
        )
    register_provider_adapter_class(key, adapter_cls, overwrite=overwrite)


def get_provider_adapter(key: str) -> ProviderAdapter:
    normalized_key = key.strip().lower()
    if normalized_key not in _PROVIDER_REGISTRY:
        raise ProviderRegistryError(f"Provider '{normalized_key}' is not registered.")
    factory = _PROVIDER_REGISTRY[normalized_key]
    return factory()


def list_provider_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDER_REGISTRY.keys()))


def reset_provider_adapter_registry() -> None:
    _PROVIDER_REGISTRY.clear()


def initialize_default_provider_adapters(*, overwrite: bool = False) -> None:
    from replaypack.providers.anthropic import AnthropicProviderAdapter
    from replaypack.providers.fake import FakeProviderAdapter
    from replaypack.providers.google import GoogleProviderAdapter
    from replaypack.providers.openai import OpenAIProviderAdapter

    defaults: dict[str, type[ProviderAdapter]] = {
        "anthropic": AnthropicProviderAdapter,
        "fake": FakeProviderAdapter,
        "google": GoogleProviderAdapter,
        "openai": OpenAIProviderAdapter,
    }
    for key, adapter_cls in defaults.items():
        if key in _PROVIDER_REGISTRY and not overwrite:
            continue
        register_provider_adapter_class(key, adapter_cls, overwrite=True)


def load_provider_adapters_from_plugins(
    plugins: dict[str, str] | None = None,
    *,
    overwrite: bool = False,
) -> None:
    """Load provider adapters from import entrypoint mapping."""
    if not plugins:
        return
    for key, entrypoint in plugins.items():
        register_provider_adapter_entrypoint(key, entrypoint, overwrite=overwrite)

