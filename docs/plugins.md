# ReplayPack Plugin Interface (v1)

ReplayPack exposes fault-isolated lifecycle hooks for capture, replay, and diff flows.

## Versions

- Plugin API version: `1.0` (`PLUGIN_API_VERSION`)
- Plugin config version: `1` (`PLUGIN_CONFIG_VERSION`)

Plugin implementations must declare `api_version` with major version `1`.

## Compatibility Rules

- Backward compatible:
  - Adding new optional fields to event payload dataclasses.
  - Adding new optional plugin hooks (default no-op on `LifecyclePlugin`).
  - Adding new plugin config keys with safe defaults.
- Breaking changes (require major plugin API bump):
  - Renaming/removing existing hook methods.
  - Changing event payload field names or semantics incompatibly.
  - Changing required plugin config schema in a non-additive way.
- Runtime behavior:
  - Plugin hook failures are isolated and recorded in diagnostics.
  - Core capture/replay/diff execution continues even if a plugin fails.

## Lifecycle Hooks

Implement `LifecyclePlugin` from `replaypack.plugins` and override any hooks you need:

- `on_capture_start(event)`
- `on_capture_step(event)`
- `on_capture_end(event)`
- `on_replay_start(event)`
- `on_replay_end(event)`
- `on_diff_start(event)`
- `on_diff_end(event)`

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

## Example Plugin

`replaypack.plugins.reference:LifecycleTracePlugin` is the reference/example plugin.
It writes hook events to NDJSON and is covered by integration tests in
`tests/test_plugins.py`.
