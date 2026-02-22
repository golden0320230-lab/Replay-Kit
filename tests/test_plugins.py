import json
from pathlib import Path

import pytest

from replaypack.capture import build_demo_run
from replaypack.diff import diff_runs
from replaypack.plugins import (
    PLUGIN_CONFIG_ENV_VAR,
    LifecyclePlugin,
    PluginConfigError,
    PluginManager,
    load_plugin_manager_from_file,
    reset_plugin_runtime_cache,
    use_plugin_manager,
)
from replaypack.replay import ReplayConfig, replay_stub_run


def _write_plugin_config(path: Path, *, output_path: Path, config_version: int = 1) -> Path:
    path.write_text(
        json.dumps(
            {
                "config_version": config_version,
                "plugins": [
                    {
                        "entrypoint": "replaypack.plugins.reference:LifecycleTracePlugin",
                        "options": {"output_path": str(output_path)},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _read_hook_trace(trace_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_reference_plugin_hooks_run_end_to_end(tmp_path: Path) -> None:
    trace_path = tmp_path / "lifecycle.ndjson"
    config_path = _write_plugin_config(tmp_path / "plugins.json", output_path=trace_path)
    manager = load_plugin_manager_from_file(config_path)

    with use_plugin_manager(manager):
        run = build_demo_run(run_id="run-plugin-e2e")
        replay_run = replay_stub_run(
            run,
            config=ReplayConfig(seed=7, fixed_clock="2026-02-22T12:00:00Z"),
        )
        diff_runs(run, replay_run)

    records = _read_hook_trace(trace_path)
    hooks = [record["hook"] for record in records]

    assert hooks.count("on_capture_start") == 1
    assert hooks.count("on_capture_step") == len(run.steps)
    assert hooks.count("on_capture_end") == 1
    assert hooks.count("on_replay_start") == 1
    assert hooks.count("on_replay_end") == 1
    assert hooks.count("on_diff_start") == 1
    assert hooks.count("on_diff_end") == 1
    assert manager.diagnostics == []

    capture_end = next(record for record in records if record["hook"] == "on_capture_end")
    replay_end = next(record for record in records if record["hook"] == "on_replay_end")
    diff_end = next(record for record in records if record["hook"] == "on_diff_end")
    assert capture_end["event"]["status"] == "ok"
    assert replay_end["event"]["status"] == "ok"
    assert diff_end["event"]["status"] == "ok"


def test_plugin_failure_is_isolated_with_diagnostics() -> None:
    class ExplodingPlugin(LifecyclePlugin):
        name = "exploding"

        def on_diff_start(self, _event) -> None:
            raise RuntimeError("boom-from-plugin")

    manager = PluginManager(plugins=(ExplodingPlugin(),))
    run = build_demo_run(run_id="run-plugin-failure")

    with use_plugin_manager(manager):
        with pytest.warns(RuntimeWarning, match="ReplayPack plugin failure"):
            result = diff_runs(run, run)

    assert result.identical is True
    assert len(manager.diagnostics) == 1
    diagnostic = manager.diagnostics[0]
    assert diagnostic.plugin_name == "exploding"
    assert diagnostic.hook == "on_diff_start"
    assert diagnostic.error_type == "RuntimeError"
    assert "boom-from-plugin" in diagnostic.message


def test_load_plugin_manager_rejects_unsupported_config_version(tmp_path: Path) -> None:
    config_path = _write_plugin_config(
        tmp_path / "plugins-invalid.json",
        output_path=tmp_path / "unused.ndjson",
        config_version=99,
    )
    with pytest.raises(PluginConfigError, match="Unsupported plugin config version"):
        load_plugin_manager_from_file(config_path)


def test_env_plugin_config_auto_activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace_path = tmp_path / "env-trace.ndjson"
    config_path = _write_plugin_config(tmp_path / "plugins-env.json", output_path=trace_path)
    monkeypatch.setenv(PLUGIN_CONFIG_ENV_VAR, str(config_path))
    reset_plugin_runtime_cache()

    build_demo_run(run_id="run-plugin-env")
    records = _read_hook_trace(trace_path)

    assert any(record["hook"] == "on_capture_start" for record in records)
    assert any(record["hook"] == "on_capture_end" for record in records)

    reset_plugin_runtime_cache()
