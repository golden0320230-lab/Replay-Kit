# Example Apps

This folder contains local-only runnable examples for ReplayKit smoke checks
and record-target workflows.

## `minimal_app.py`

`minimal_app.py` starts a local stdlib HTTP server on an ephemeral `127.0.0.1`
port, then sends one `requests` call and one `httpx` call to it.

It does not require external network access.

Run it directly:

```bash
python3 examples/apps/minimal_app.py
```

Use it with ReplayKit commands:

```bash
replaykit record --out runs/manual/example-demo.rpk
replaykit replay runs/manual/example-demo.rpk --out runs/manual/example-replay.rpk
replaykit diff runs/manual/example-demo.rpk runs/manual/example-replay.rpk --first-divergence
```

## Record Target Script Example

`record_target_script.py` demonstrates script-mode recording with:

- local stdlib HTTP server
- one `requests` call
- one `httpx` call

Commands:

```bash
python3 examples/apps/record_target_script.py
replaykit record --out runs/manual/record-script.rpk -- python examples/apps/record_target_script.py
```

## Record Target Module Example

`record_target_module` demonstrates module-mode recording with:

- local stdlib HTTP server
- one `requests` call
- one `httpx` call
- optional tool boundary via `@replaykit.tool`

Commands:

```bash
python3 -m examples.apps.record_target_module
replaykit record --out runs/manual/record-module.rpk -- python -m examples.apps.record_target_module
python3 -m replaykit.bootstrap --out runs/manual/bootstrap-module.rpk -- -m examples.apps.record_target_module
```

All commands are local-only and require no external network.
