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
- Versioned plugin hooks for capture/replay/diff lifecycle

## Planned CLI Surface

```bash
replaykit record -- python app.py
replaykit replay runs/2026-02-21-120000.rpk
replaykit diff runs/a.rpk runs/b.rpk --first-divergence
replaykit bundle runs/a.rpk --redact default --out incident.bundle
replaykit verify runs/a.rpk
replaykit assert baseline.rpk
replaykit live-compare baseline.rpk --live-demo
replaykit snapshot my-flow --candidate runs/candidate.rpk
replaykit benchmark --source examples/runs/m2_capture_boundaries.rpk
replaykit migrate runs/legacy-0.9.rpk --out runs/migrated.rpk
replaykit ui
```

Global output modes:

```bash
replaykit --quiet assert runs/baseline.rpk --candidate runs/candidate.rpk
replaykit --no-color diff runs/a.rpk runs/b.rpk
replaykit --stable-json assert runs/baseline.rpk --candidate runs/candidate.rpk --json
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

Load custom redaction rules (record/bundle/diff):

```bash
cat > redaction.policy.json <<'JSON'
{
  "version": "team-policy-v1",
  "extra_sensitive_field_names": ["x-trace-id", "session_id"],
  "extra_secret_value_patterns": ["\\bghp_[A-Za-z0-9]{20,}\\b"],
  "extra_sensitive_path_patterns": ["^/metadata/internal_trace$"]
}
JSON

replaykit record --out runs/demo-custom.rpk --redaction-config redaction.policy.json
replaykit bundle runs/demo-custom.rpk --out runs/incident-custom.bundle --redaction-config redaction.policy.json
replaykit diff runs/demo-custom.rpk runs/replay-output.rpk --redaction-config redaction.policy.json --json
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

Run live compare against baseline (generate a live demo run and diff/assert it):

```bash
replaykit live-compare runs/baseline.rpk --live-demo --out runs/live-candidate.rpk --json
```

Create/update and assert a snapshot baseline artifact:

```bash
replaykit snapshot my-flow --candidate runs/candidate.rpk --snapshots-dir snapshots --update
replaykit snapshot my-flow --candidate runs/candidate.rpk --snapshots-dir snapshots --json
```

Run performance benchmark suite and optional slowdown gate:

```bash
replaykit benchmark --source examples/runs/m2_capture_boundaries.rpk --iterations 3 --out runs/benchmark.json --json
replaykit benchmark --source examples/runs/m2_capture_boundaries.rpk --iterations 3 --out runs/benchmark-current.json --baseline runs/benchmark-baseline.json --fail-on-slowdown 30 --json
```

Migrate legacy artifacts to current schema:

```bash
replaykit migrate runs/legacy-0.9.rpk --out runs/migrated.rpk --json
```

Run deterministic fuzz smoke tests (canonicalization, parser, diff):

```bash
python3 -m pytest -q tests/test_fuzz_stability.py
```

Enable strict drift checks (environment/runtime metadata + step metadata):

```bash
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --strict --json
```

Enable slowdown gate in assertion (requires duration metadata in artifacts):

```bash
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --fail-on-slowdown 25 --json
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

Activate lifecycle plugins with a versioned plugin config:

```bash
cat > plugins.json <<'JSON'
{
  "config_version": 1,
  "plugins": [
    {
      "entrypoint": "replaypack.plugins.reference:LifecycleTracePlugin",
      "options": {"output_path": "runs/plugins/lifecycle.ndjson"}
    }
  ]
}
JSON

REPLAYKIT_PLUGIN_CONFIG=plugins.json replaykit diff runs/demo-recording.rpk runs/replay-output.rpk --json
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
