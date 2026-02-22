# ReplayKit Replay Engine

## Scope

- Deterministic offline stub replay for recorded `.rpk` artifacts.
- Hybrid replay for selective rerun boundaries while stubbing the rest.

## Stub Replay Semantics

- No external API calls are made.
- Recorded step order is preserved.
- Recorded step outputs are returned as replay outputs.
- Replay writes a new deterministic artifact that includes replay metadata.

## Public API

- `ReplayConfig(seed, fixed_clock)`
- `HybridReplayPolicy(rerun_step_types, rerun_step_ids, strict_alignment)`
- `replay_stub_run(source_run, config=...)`
- `replay_hybrid_run(source_run, rerun_run, config=..., policy=...)`
- `write_replay_stub_artifact(source_run, out_path, config=...)`
- `write_replay_hybrid_artifact(source_run, rerun_run, out_path, config=..., policy=...)`

## Determinism Controls

- `seed`: controls replay runtime RNG state
- `fixed_clock`: forces replay run timestamp and metadata clock

Given identical source run + seed + fixed clock, replay output artifacts are byte-identical.

## Offline Guarantees

Replay path uses an offline network guard that blocks outbound socket connection attempts.

If replay internals or adapters attempt a network call, replay fails immediately.

## CLI Usage

Stub replay:

```bash
replaykit replay examples/runs/m2_capture_boundaries.rpk \
  --out runs/replay-output.rpk \
  --seed 42 \
  --fixed-clock 2026-02-21T18:00:00Z
```

Machine-readable output:

```bash
replaykit replay examples/runs/m2_capture_boundaries.rpk --json
```

Hybrid replay using rerun source artifact and step-type selectors:

```bash
replaykit replay examples/runs/m2_capture_boundaries.rpk \
  --mode hybrid \
  --rerun-from runs/manual/rerun-candidate.rpk \
  --rerun-type model.response \
  --out runs/manual/hybrid-output.rpk \
  --seed 42 \
  --fixed-clock 2026-02-21T18:00:00Z
```

Guardrail modes:

```bash
replaykit replay examples/runs/m2_capture_boundaries.rpk --nondeterminism warn
replaykit replay examples/runs/m2_capture_boundaries.rpk --nondeterminism fail --json
```

## Assumptions and Limits

- Hybrid mode uses a second artifact as rerun source and currently aligns by step index.
- Hybrid mode requires explicit selectors (`--rerun-type` and/or `--rerun-step-id`).
- Replay currently operates on existing artifacts rather than instrumenting live application execution.
- Adapter-level runtime interception for SDKs/frameworks is planned in later milestones.
