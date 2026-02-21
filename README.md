# ReplayKit

ReplayKit is a local-first debugging toolkit for AI workflows. It records executions into deterministic artifacts, replays them offline, and diffs runs to identify the first point of divergence.

## Why ReplayKit

AI behavior changes are hard to root-cause because prompts, model settings, tool responses, and retrieval state all drift over time.

ReplayKit is designed to answer one question quickly:

> Why did this run behave differently?

## Core Principles

- Plug-and-play CLI experience
- Deterministic, offline replay
- First-divergence detection
- Provider-agnostic capture and replay
- Cross-platform behavior (macOS, Linux, Windows)
- Security-first redaction defaults

## Planned CLI Surface

```bash
replaykit record -- python app.py
replaykit replay runs/2026-02-21-120000.rpk
replaykit diff runs/a.rpk runs/b.rpk --first-divergence
replaykit bundle runs/a.rpk --redact default --out incident.bundle
replaykit assert baseline.rpk
replaykit ui
```

## Repository Scaffold

```text
docs/                 Architecture and project docs
replaypack/           Python package (core modules)
  core/
  capture/
  artifact/
  replay/
  diff/
  cli/
  ui/
GOALS.md              Project goals and task tracking
pyproject.toml        Package metadata and CLI entrypoint
```

## Current Status

- `M1` is complete: deterministic artifact schema, canonicalization, and hashing.
- `M2` capture engine is in progress with model/tool/HTTP wrappers and policy-based redaction.

You can generate a deterministic demo capture artifact with:

```bash
replaykit record --out runs/demo-recording.rpk
```

## License

MIT
