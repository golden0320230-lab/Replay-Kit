"""Agent adapter registry and plugin hooks."""

from __future__ import annotations

import importlib
from typing import Callable

from replaypack.agents.base import AgentAdapter

AgentFactory = Callable[[], AgentAdapter]
_AGENT_REGISTRY: dict[str, AgentFactory] = {}


class AgentRegistryError(ValueError):
    """Raised when agent adapter registration fails."""


def register_agent_adapter(
    key: str,
    factory: AgentFactory,
    *,
    overwrite: bool = False,
) -> None:
    normalized_key = key.strip().lower()
    if not normalized_key:
        raise AgentRegistryError("Agent key cannot be empty.")
    if not overwrite and normalized_key in _AGENT_REGISTRY:
        raise AgentRegistryError(f"Agent '{normalized_key}' is already registered.")
    _AGENT_REGISTRY[normalized_key] = factory


def register_agent_adapter_class(
    key: str,
    adapter_cls: type[AgentAdapter],
    *,
    overwrite: bool = False,
) -> None:
    register_agent_adapter(key, adapter_cls, overwrite=overwrite)


def register_agent_adapter_entrypoint(
    key: str,
    entrypoint: str,
    *,
    overwrite: bool = False,
) -> None:
    module_name, separator, attr = entrypoint.partition(":")
    if not separator:
        raise AgentRegistryError(
            f"Invalid agent adapter entrypoint '{entrypoint}'. Expected module:attribute."
        )
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    if isinstance(target, type):
        adapter_cls = target
    elif callable(target):
        adapter = target()
        adapter_cls = type(adapter)
    else:
        raise AgentRegistryError(
            f"Agent adapter entrypoint '{entrypoint}' is not callable."
        )
    register_agent_adapter_class(key, adapter_cls, overwrite=overwrite)


def get_agent_adapter(key: str) -> AgentAdapter:
    normalized_key = key.strip().lower()
    if normalized_key not in _AGENT_REGISTRY:
        raise AgentRegistryError(f"Agent '{normalized_key}' is not registered.")
    factory = _AGENT_REGISTRY[normalized_key]
    return factory()


def list_agent_adapter_keys() -> tuple[str, ...]:
    return tuple(sorted(_AGENT_REGISTRY.keys()))


def reset_agent_adapter_registry() -> None:
    _AGENT_REGISTRY.clear()


def initialize_default_agent_adapters(*, overwrite: bool = False) -> None:
    from replaypack.agents.claude_code import ClaudeCodeAgentAdapter
    from replaypack.agents.codex import CodexAgentAdapter

    defaults: dict[str, type[AgentAdapter]] = {
        "claude-code": ClaudeCodeAgentAdapter,
        "codex": CodexAgentAdapter,
    }
    for key, adapter_cls in defaults.items():
        if key in _AGENT_REGISTRY and not overwrite:
            continue
        register_agent_adapter_class(key, adapter_cls, overwrite=True)


def load_agent_adapters_from_plugins(
    plugins: dict[str, str] | None = None,
    *,
    overwrite: bool = False,
) -> None:
    """Load agent adapters from import entrypoint mapping."""
    if not plugins:
        return
    for key, entrypoint in plugins.items():
        register_agent_adapter_entrypoint(key, entrypoint, overwrite=overwrite)

