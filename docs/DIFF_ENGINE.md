# ReplayKit Diff Engine (M4)

## Scope

M4 adds deterministic run comparison with first-divergence detection.

## Algorithm

`diff_runs(left, right)` compares steps by index order in a single pass.

- Time complexity: `O(n)` by step count
- Space complexity: `O(n)` for emitted diff entries

Where `n = max(len(left.steps), len(right.steps))`.

## Step Comparison Rules

At each step index:

- `identical`: same step `type` and `hash`
- `changed`: both steps exist but differ
- `missing_left`: step exists only in right run
- `missing_right`: step exists only in left run

For changed steps, field-level deltas are emitted using JSON pointer paths:

- `/input/...`
- `/output/...`
- `/metadata/...`

## First Divergence

The first step with status not equal to `identical` is marked as first divergence.

CLI `--first-divergence` mode stops immediately when this step is found.

## Context Surface

Diff output includes step context when available:

- `model`
- `provider`
- `tool`
- `method`
- `url`
- `temperature`
- `max_tokens`

## CLI Usage

```bash
replaykit diff examples/runs/m2_capture_boundaries.rpk examples/runs/m4_diverged_from_m2.rpk
```

First-divergence only:

```bash
replaykit diff examples/runs/m2_capture_boundaries.rpk examples/runs/m4_diverged_from_m2.rpk --first-divergence
```

Machine-readable JSON:

```bash
replaykit diff examples/runs/m2_capture_boundaries.rpk examples/runs/m4_diverged_from_m2.rpk --json
```
