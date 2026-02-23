from __future__ import annotations

from pathlib import Path

from replaypack.agents import (
    get_agent_adapter,
    initialize_default_agent_adapters,
    list_agent_adapter_keys,
    load_agent_adapters_from_plugins,
    reset_agent_adapter_registry,
)


def test_agent_registry_defaults_include_required_keys() -> None:
    keys = list_agent_adapter_keys()
    assert "codex" in keys
    assert "claude-code" in keys


def test_agent_registry_plugin_hook_registers_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_module = tmp_path / "agent_plugin_fixture.py"
    plugin_module.write_text(
        "\n".join(
            [
                "from replaypack.agents.base import AgentAdapter, AgentLaunchResult",
                "",
                "class FixtureAgentAdapter(AgentAdapter):",
                "    name = 'fixture-agent'",
                "",
                "    def launch(self, *, run_id, command):",
                "        return AgentLaunchResult(run_id=run_id, command=tuple(command), returncode=0, stdout='', stderr='', events=[])",
                "",
                "    def normalize_tool_event(self, event):",
                "        return {'agent': self.name, 'event': event}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    reset_agent_adapter_registry()
    initialize_default_agent_adapters()
    try:
        load_agent_adapters_from_plugins(
            {"fixture-agent": "agent_plugin_fixture:FixtureAgentAdapter"}
        )
        keys = list_agent_adapter_keys()
        assert "fixture-agent" in keys
        assert get_agent_adapter("fixture-agent").name == "fixture-agent"
    finally:
        reset_agent_adapter_registry()
        initialize_default_agent_adapters()

