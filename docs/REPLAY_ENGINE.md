# ReplayKit Replay Engine (M3)

## Scope

M3 adds deterministic offline stub replay for recorded `.rpk` artifacts.

## Stub Replay Semantics

- No external API calls are made.
- Recorded step order is preserved.
- Recorded step outputs are returned as replay outputs.
- Replay writes a new deterministic artifact that includes replay metadata.

## Public API

- `ReplayConfig(seed, fixed_clock)`
- `replay_stub_run(source_run, config=...)`
- `write_replay_stub_artifact(source_run, out_path, config=...)`

## Determinism Controls

- `seed`: controls replay runtime RNG state
- `fixed_clock`: forces replay run timestamp and metadata clock

Given identical source run + seed + fixed clock, replay output artifacts are byte-identical.

## Offline Guarantees

Replay path uses an offline network guard that blocks outbound socket connection attempts.

If replay internals or adapters attempt a network call, replay fails immediately.

## CLI Usage

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

## Assumptions and Limits

- M3 is stub replay only; hybrid selective rerun is out of scope.
- Replay currently operates on existing artifacts rather than instrumenting live application execution.
- Adapter-level runtime interception for SDKs/frameworks is planned in later milestones.
