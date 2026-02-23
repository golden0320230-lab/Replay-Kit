# ReplayKit

[![CI](https://github.com/golden0320230-lab/Replay-Kit/actions/workflows/ci.yml/badge.svg)](https://github.com/golden0320230-lab/Replay-Kit/actions/workflows/ci.yml)

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

## Compatibility & Stability

- Supported Python versions: **3.10+** (declared in `pyproject.toml`; CI currently runs Python 3.12).
- Platform guarantees: ReplayKit is validated in CI on **Linux**, **macOS**, and **Windows**.
- Semantic versioning policy: ReplayKit follows **SemVer** (`MAJOR.MINOR.PATCH`) for user-facing behavior.
- Backward compatibility guarantees:
  - Public library API stability is defined in `docs/PUBLIC_API.md`.
  - Breaking API changes require a major version bump.
  - Artifact schema changes must include migration support.

## Current Capabilities

As of **February 22, 2026**, ReplayKit currently provides:

- Deterministic run capture to `.rpk` artifacts, including a built-in demo flow and wrapper capture for external script/module execution.
- Boundary-level capture for `model.*`, `tool.*`, and HTTP (`requests` + `httpx`) workflows with stable canonicalization and hashing.
- Fully offline replay in `stub` mode, plus `hybrid` replay with selective rerun controls (`--rerun-type` and `--rerun-step-id`).
- O(n) structured diff with first-divergence detection for fast root-cause isolation.
- Regression-style `assert` checks with JSON output, optional strict drift checks, and optional slowdown gate thresholds.
- Redacted bundle export, artifact migration, and HMAC signing/verification for integrity and incident sharing.
- Snapshot update/assert workflow (`snapshot`) and benchmark workflow (`benchmark`) for repeatable local/CI validation.
- Local UI (`ui`) with left/right artifact prefill and browser launch support for Git-style run comparisons.
- Live demo capture mode (`live-demo`) with deterministic fake provider behavior, including optional streaming shape capture.
- Provider adapter contract (`docs/providers.md`) for custom model providers without modifying core capture internals.
- Lifecycle plugin hooks via versioned plugin config (`docs/plugins.md`) for capture/replay/diff events.
- Stable Python API entrypoint (`import replaykit`) and tool decorator capture (`@replaykit.tool`) for library integrations.
- Cross-platform CI coverage (macOS, Linux, Windows) with golden-path record/replay/assert/diff checks in GitHub Actions.
- Replay determinism validation in CI via dual replay artifacts compared with `assert`.
- Replay network-guard validation in CI via dedicated golden-path replay e2e coverage.

## Quickstart (Runnable Now)

```bash
python3 -m pip install -e ".[dev]"
python3 examples/apps/minimal_app.py
replaykit record --out runs/quickstart-demo.rpk
replaykit record --out runs/app.rpk -- python examples/apps/minimal_app.py
replaykit record --out runs/quickstart-module.rpk -- python -m replaypack.capture.demo
replaykit replay runs/quickstart-demo.rpk --out runs/quickstart-replay.rpk
replaykit diff runs/quickstart-demo.rpk runs/quickstart-replay.rpk --first-divergence
```

## Target Record Mode (Runnable Now)

Use target-record mode today without app code changes:

```bash
replaykit record --out runs/app.rpk -- python examples/apps/minimal_app.py
```

Default wrapper interception scope:

- Captured automatically: `requests` and `httpx`.
- Not captured automatically: provider SDK calls unless an adapter/hook is enabled.

## Installation

Install from source (current workflow):

```bash
pip install -e .
```

Install from source with dev/test extras:

```bash
python3 -m pip install -e ".[dev]"
```

Install from PyPI (when published):

```bash
pip install replaykit
```

Check installed CLI version:

```bash
replaykit --version
```

## CLI Surface

```bash
replaykit --version
replaykit record -- python app.py
replaykit record --out runs/app.rpk -- python examples/apps/minimal_app.py
replaykit record --out runs/mod.rpk -- python -m replaypack.capture.demo
python3 -m replaykit.bootstrap --out runs/bootstrap.rpk -- examples/apps/minimal_app.py
replaykit replay runs/2026-02-21-120000.rpk
replaykit diff runs/a.rpk runs/b.rpk --first-divergence
replaykit bundle runs/a.rpk --redact default --out incident.bundle
replaykit verify runs/a.rpk
replaykit assert baseline.rpk
replaykit live-demo --out runs/live-demo.rpk --provider fake --stream
replaykit llm --provider fake --model fake-chat --prompt "say hello" --stream --out runs/llm-capture.rpk
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
- Post-`M7` update: CLI wrapper record-target support with local-only script/module examples.
- Post-`M7` update: interceptor leak-proofing coverage (HTTP patches uninstall cleanly after capture).
- Post-`M7` update: live fake-provider capture mode (`replaykit live-demo`) with stream/non-stream parity.
- Post-`M7` update: provider adapter contract and reference adapter (`docs/providers.md`).
- Post-`M7` update: release polish (`replaykit --version`, install/signing docs).
- Post-`M7` update: CI golden-path gating in GitHub Actions (record/replay/assert/diff + replay network guard).

Generate a deterministic capture artifact:

```bash
replaykit record --out runs/demo-recording.rpk
```

Record an arbitrary Python app (no app code changes):

```bash
replaykit record --out runs/app.rpk -- python examples/apps/minimal_app.py
replaykit record --out runs/mod.rpk -- python -m replaypack.capture.demo
```

Current wrapper interception scope:

- Captured automatically: `requests` and `httpx` HTTP boundaries.
- Not captured automatically: provider SDKs beyond current adapters unless explicitly integrated.

Bootstrap in-process capture directly (script or module):

```bash
python3 -m replaykit.bootstrap --out runs/bootstrap-script.rpk -- examples/apps/minimal_app.py
python3 -m replaykit.bootstrap --out runs/bootstrap-module.rpk -- -m replaypack.capture.demo
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

Signing environment variables:

- `REPLAYKIT_SIGNING_KEY`: HMAC signing key used by `record --sign` and `bundle --sign`.
- `REPLAYKIT_SIGNING_KEY_ID`: optional key identifier included in signature metadata.

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

Capture provider-shaped LLM calls without wrapping a target app:

```bash
replaykit llm --provider fake --model fake-chat --prompt "say hello" --stream --out runs/llm-capture.rpk
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

Library integration capture context (no CLI):

```python
import replaykit

@replaykit.tool(name="demo.echo")
def echo(value: str) -> dict[str, str]:
    return {"echo": value}

with replaykit.record("runs/library-capture.rpk", intercept=("requests", "httpx")):
    echo("hello")
```

Public API compatibility policy and semver guarantees:

- `docs/PUBLIC_API.md`
- `docs/plugins.md`

Release and upgrade policy:

- `CHANGELOG.md`
- `docs/RELEASES.md`

## License

MIT
