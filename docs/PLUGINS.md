# ReplayPack Plugin System (v1)

ReplayPack exposes fault-isolated lifecycle hooks for capture, replay, and diff flows.

## Versions

- Plugin API version: `1.0` (`PLUGIN_API_VERSION`)
- Plugin config version: `1` (`PLUGIN_CONFIG_VERSION`)

Plugin implementations must declare `api_version` with major version `1` (for example `1.0`).

## Lifecycle Hooks

Implement `LifecyclePlugin` from `replaypack.plugins` and override any hook methods you need:

- `on_capture_start(event)`
- `on_capture_step(event)`
- `on_capture_end(event)`
- `on_replay_start(event)`
- `on_replay_end(event)`
- `on_diff_start(event)`
- `on_diff_end(event)`

Hook failures are isolated. Core capture/replay/diff execution continues, and diagnostics are recorded in `PluginManager.diagnostics`.
Runtime warnings also include plugin name + hook + error message for quick troubleshooting.

## Config Format

```json
{
  "config_version": 1,
  "plugins": [
    {
      "entrypoint": "replaypack.plugins.reference:LifecycleTracePlugin",
      "options": {
        "output_path": "runs/plugins/lifecycle.ndjson"
      },
      "enabled": true
    }
  ]
}
```

## Loading Model

API-driven activation:

```python
from replaypack.capture import build_demo_run
from replaypack.diff import diff_runs
from replaypack.plugins import load_plugin_manager_from_file, use_plugin_manager
from replaypack.replay import replay_stub_run

manager = load_plugin_manager_from_file("plugins.json")
with use_plugin_manager(manager):
    run = build_demo_run()
    replayed = replay_stub_run(run)
    diff = diff_runs(run, replayed)
```

Environment-driven activation:

- Set `REPLAYKIT_PLUGIN_CONFIG=/path/to/plugins.json`
- Any capture/replay/diff call in that process uses loaded plugins automatically.

## Reference Plugin

`LifecycleTracePlugin` writes each hook call to NDJSON (`hook`, `plugin`, `event`) and is intended as a template for enterprise integrations.
