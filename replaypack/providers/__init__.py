"""Provider adapter contracts and reference implementations."""

from replaypack.providers.base import ProviderAdapter, assemble_stream_capture
from replaypack.providers.anthropic import AnthropicProviderAdapter
from replaypack.providers.fake import FakeProviderAdapter
from replaypack.providers.google import GoogleProviderAdapter
from replaypack.providers.openai import OpenAIProviderAdapter
from replaypack.providers.registry import (
    ProviderRegistryError,
    get_provider_adapter,
    initialize_default_provider_adapters,
    list_provider_adapter_keys,
    load_provider_adapters_from_plugins,
    register_provider_adapter,
    register_provider_adapter_class,
    register_provider_adapter_entrypoint,
    reset_provider_adapter_registry,
)

initialize_default_provider_adapters()

__all__ = [
    "ProviderAdapter",
    "AnthropicProviderAdapter",
    "FakeProviderAdapter",
    "GoogleProviderAdapter",
    "OpenAIProviderAdapter",
    "ProviderRegistryError",
    "get_provider_adapter",
    "initialize_default_provider_adapters",
    "list_provider_adapter_keys",
    "load_provider_adapters_from_plugins",
    "register_provider_adapter",
    "register_provider_adapter_class",
    "register_provider_adapter_entrypoint",
    "reset_provider_adapter_registry",
    "assemble_stream_capture",
]
