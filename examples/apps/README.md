# Example Apps

This folder contains local-only runnable examples for ReplayKit smoke checks.

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
