# ReplayKit Architecture (v0.1 Draft)

## North Star

ReplayKit exists to make AI behavior regressions reproducible and explainable.

Primary question:

> Why did this system behave differently this time?

## Product Pillars

- Plug-and-play
- Debug-first
- Cross-platform
- Provider-agnostic
- Local-first and offline-capable

## Module Boundaries

### `capture`

Responsibility:
- Intercept model calls, tool calls, and HTTP boundaries
- Emit ordered, typed steps

Interface:
- `start_run(...) -> RunContext`
- `record_step(...) -> Step`
- `end_run(...) -> Run`

Extension points:
- Provider adapters
- Tool interceptors
- HTTP middleware/hooks

Failure surfaces:
- Unsupported SDK versions
- Streaming response assembly mismatches
- Non-deterministic payload ordering

Invariants:
- Step order must be stable
- Step types must be explicit
- Sensitive values must be redacted by policy

### `artifact`

Responsibility:
- Serialize and load `.rpk` artifacts deterministically

Interface:
- `write_artifact(run, path)`
- `read_artifact(path) -> Run`

Extension points:
- Compression mode
- Versioned schema migration
- Redaction transforms

Failure surfaces:
- Schema drift
- Unstable canonicalization
- Cross-platform encoding/path issues

Invariants:
- Stable key ordering
- Stable hash inputs
- Backward-compatible versioning strategy

### `replay`

Responsibility:
- Execute stub/hybrid replay from artifacts

Interface:
- `replay_stub(path)`
- `replay_hybrid(path, policy)`

Extension points:
- Step rerun policies
- Latency simulation
- Selective provider/tool rerun

Failure surfaces:
- Missing step dependencies
- Replay state mismatch
- External call leakage in offline mode

Invariants:
- Stub mode never performs external network calls
- Recorded step ordering is preserved
- Replayed outputs are deterministic

### `diff`

Responsibility:
- Compare two runs in O(n) step order
- Identify first divergence

Interface:
- `diff_runs(left, right) -> DiffResult`
- `first_divergence(diff) -> StepDiff | None`

Extension points:
- Text and JSON diff strategies
- Ignore rules for non-semantic metadata

Failure surfaces:
- False positives from unstable normalization
- False negatives from missing fields

Invariants:
- First divergence is earliest true semantic mismatch
- Comparison is deterministic and step-order aware

### `cli`

Responsibility:
- Provide user-facing command surface

Commands (planned):
- `record`
- `replay`
- `diff`
- `bundle`
- `assert`
- `ui`

Invariants:
- Clear error messaging
- Machine-readable exit codes for CI

### `ui`

Responsibility:
- Local Git-diff-style run inspection

Layout targets:
- Left: step list and status
- Center: side-by-side diff
- Right: metadata and first-divergence summary

Invariants:
- Local-only by default
- Reads artifacts from disk

## Core Data Model

### Run

- `id`
- `timestamp`
- `environment_fingerprint`
- `runtime_versions`
- `steps[]`

### Step

- `id`
- `type`
- `input`
- `output`
- `metadata`
- `hash`

Supported step types:

- `prompt.render`
- `model.request`
- `model.response`
- `tool.request`
- `tool.response`
- `error.event`
- `output.final`

## Determinism and Security Rules

- Replay must work fully offline
- Step hashing must be stable across repeated runs
- Diff must identify first divergence accurately
- No secret leakage in artifacts/bundles
- No telemetry by default

## Delivery Sequence

1. Artifact schema + canonicalization
2. Capture primitives + step hashing
3. Stub replay engine
4. O(n) diff and first divergence
5. CLI workflow hardening
6. Local UI implementation
