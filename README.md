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
replaykit verify runs/a.rpk
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
- `M5` complete: redacted bundle export profiles with replay-safe bundle round-trip.
- `M6` complete: CI-oriented assertion command and workflow integration.
- `M7` complete: local Git-diff style UI with first-divergence navigation.

Generate a deterministic capture artifact:

```bash
replaykit record --out runs/demo-recording.rpk
```

Replay it offline into a deterministic output artifact:

```bash
replaykit replay runs/demo-recording.rpk --out runs/replay-output.rpk --seed 42 --fixed-clock 2026-02-21T18:00:00Z
```

Run hybrid replay (rerun selected boundaries from another run, stub everything else):

```bash
replaykit replay runs/demo-recording.rpk \
  --mode hybrid \
  --rerun-from runs/manual/rerun-candidate.rpk \
  --rerun-type model.response \
  --out runs/hybrid-output.rpk
```

Diff two artifacts and stop at first divergence:

```bash
replaykit diff runs/demo-recording.rpk runs/replay-output.rpk --first-divergence
```

Export a shareable redacted bundle:

```bash
replaykit bundle runs/demo-recording.rpk --out runs/incident.bundle --redact default
```

Sign artifacts during record/bundle and verify signature integrity:

```bash
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit record --out runs/signed-recording.rpk --sign
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit verify runs/signed-recording.rpk --json
```

Assert candidate behavior against a baseline artifact (CI-friendly exit codes):

```bash
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --json
```

Enable strict drift checks (environment/runtime metadata + step metadata):

```bash
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --strict --json
```

Enable determinism guardrails in assert/replay paths:

```bash
replaykit replay runs/demo-recording.rpk --nondeterminism warn
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --nondeterminism fail --json
```

Launch the local UI:

```bash
replaykit ui --left examples/runs/m2_capture_boundaries.rpk --right examples/runs/m4_diverged_from_m2.rpk
```

Stable Python API import:

```python
import replaykit

replaykit.record("runs/demo.rpk")
replaykit.replay(
    "runs/demo.rpk",
    out="runs/hybrid-demo.rpk",
    mode="hybrid",
    rerun_from="runs/manual/rerun-candidate.rpk",
    rerun_step_types=("model.response",),
)
result = replaykit.diff("examples/runs/m2_capture_boundaries.rpk", "examples/runs/m4_diverged_from_m2.rpk")
print(result.first_divergence.index if result.first_divergence else "no divergence")
```

## License

MIT
