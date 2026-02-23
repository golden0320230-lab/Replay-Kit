"""Agent adapter registry and built-in adapters."""

from replaypack.agents.base import AgentAdapter, AgentLaunchResult
from replaypack.agents.claude_code import ClaudeCodeAgentAdapter
from replaypack.agents.codex import CodexAgentAdapter
from replaypack.agents.registry import (
    AgentRegistryError,
    get_agent_adapter,
    initialize_default_agent_adapters,
    list_agent_adapter_keys,
    load_agent_adapters_from_plugins,
    register_agent_adapter,
    register_agent_adapter_class,
    register_agent_adapter_entrypoint,
    reset_agent_adapter_registry,
)

initialize_default_agent_adapters()

__all__ = [
    "AgentAdapter",
    "AgentLaunchResult",
    "AgentRegistryError",
    "ClaudeCodeAgentAdapter",
    "CodexAgentAdapter",
    "get_agent_adapter",
    "initialize_default_agent_adapters",
    "list_agent_adapter_keys",
    "load_agent_adapters_from_plugins",
    "register_agent_adapter",
    "register_agent_adapter_class",
    "register_agent_adapter_entrypoint",
    "reset_agent_adapter_registry",
]

