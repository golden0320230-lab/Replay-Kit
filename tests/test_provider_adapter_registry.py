from __future__ import annotations

from pathlib import Path

from replaypack.providers import (
    get_provider_adapter,
    initialize_default_provider_adapters,
    list_provider_adapter_keys,
    load_provider_adapters_from_plugins,
    reset_provider_adapter_registry,
)


def test_provider_registry_defaults_include_required_keys() -> None:
    keys = list_provider_adapter_keys()
    assert "openai" in keys
    assert "anthropic" in keys
    assert "google" in keys


def test_provider_registry_plugin_hook_registers_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_module = tmp_path / "provider_plugin_fixture.py"
    plugin_module.write_text(
        "\n".join(
            [
                "from replaypack.capture import DEFAULT_REDACTION_POLICY, redact_payload",
                "from replaypack.providers.base import ProviderAdapter",
                "",
                "class FixtureProviderAdapter(ProviderAdapter):",
                "    name = 'fixture-provider'",
                "",
                "    def normalize_request(self, *, model, payload, headers=None, url=None, stream=False):",
                "        return {'provider': self.name, 'model': model, 'payload': payload, 'stream': stream, 'headers': headers or {}, 'url': url}",
                "",
                "    def normalize_stream_chunk(self, *, chunk):",
                "        return {'provider': self.name, 'chunk': chunk, 'delta_text': ''}",
                "",
                "    def normalize_response(self, *, response):",
                "        return {'provider': self.name, 'response': response, 'stream': False}",
                "",
                "    def redact(self, payload, *, policy=DEFAULT_REDACTION_POLICY):",
                "        return redact_payload(payload, policy=policy)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    reset_provider_adapter_registry()
    initialize_default_provider_adapters()
    try:
        load_provider_adapters_from_plugins(
            {"fixture-provider": "provider_plugin_fixture:FixtureProviderAdapter"}
        )
        keys = list_provider_adapter_keys()
        assert "fixture-provider" in keys
        assert get_provider_adapter("fixture-provider").name == "fixture-provider"
    finally:
        reset_provider_adapter_registry()
        initialize_default_provider_adapters()

