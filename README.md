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

- `M1` complete: deterministic artifact schema, canonicalization, and hashing.
- `M2` complete: capture engine boundaries (model/tool/http) with policy-driven redaction.
- `M3` complete: offline stub replay with deterministic seed/clock controls.
- `M4` complete: O(n) diff engine with first-divergence detection and CLI rendering.

Generate a deterministic capture artifact:

```bash
replaykit record --out runs/demo-recording.rpk
```

Replay it offline into a deterministic output artifact:

```bash
replaykit replay runs/demo-recording.rpk --out runs/replay-output.rpk --seed 42 --fixed-clock 2026-02-21T18:00:00Z
```

Diff two artifacts and stop at first divergence:

```bash
replaykit diff runs/demo-recording.rpk runs/replay-output.rpk --first-divergence
```

## License

MIT
