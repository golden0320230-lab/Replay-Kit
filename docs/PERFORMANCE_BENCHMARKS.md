# Performance Benchmarks and Slowdown Gates

## Purpose

ReplayKit includes:

- a benchmark suite for representative `record`, `replay`, and `diff` workloads
- slowdown gates for benchmark comparisons and assertion workflows

## Benchmark Command

Run benchmark suite and write summary artifact:

```bash
replaykit benchmark \
  --source examples/runs/m2_capture_boundaries.rpk \
  --iterations 3 \
  --out runs/benchmark.json \
  --json
```

Compare against a baseline benchmark and fail on slowdown threshold:

```bash
replaykit benchmark \
  --source examples/runs/m2_capture_boundaries.rpk \
  --iterations 3 \
  --out runs/benchmark-current.json \
  --baseline runs/benchmark-baseline.json \
  --fail-on-slowdown 30 \
  --json
```

## Assertion Slowdown Gate

You can enforce duration regressions directly in `assert`:

```bash
replaykit assert baseline.rpk --candidate candidate.rpk --fail-on-slowdown 25 --json
```

This uses per-step metadata duration fields:

- `duration_ms`
- `latency_ms`
- `wall_time_ms`
- `elapsed_ms`

If the gate is requested and timing metadata is missing, assertion fails with
`performance.status=missing_metrics`.
