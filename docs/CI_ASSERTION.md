# CI Regression Assertion (M6)

## Purpose

`replaykit assert` provides CI-safe pass/fail semantics for behavior regression checks.

- exit `0`: baseline and candidate are identical
- exit `1`: divergence detected or input error

## CLI Usage

```bash
replaykit assert baseline.rpk --candidate candidate.rpk
```

Machine-readable output:

```bash
replaykit assert baseline.rpk --candidate candidate.rpk --json
```

Strict-mode drift gating:

```bash
replaykit assert baseline.rpk --candidate candidate.rpk --strict --json
```

## Local Reproduction (matches CI)

```bash
python3 -m pip install -e .
python3 -m pytest -q
mkdir -p runs
python3 -m replaypack assert examples/runs/m2_capture_boundaries.rpk \
  --candidate examples/runs/m2_capture_boundaries.rpk \
  --json > runs/ci-assert.json
```

## CI Artifact Paths

- `runs/ci-assert.json` assertion output
- `runs/` directory uploaded as workflow artifact on every run

## Failure Diagnostics

On divergence, output includes:

- first divergence step index
- left/right step ids and types
- high-signal context (model/tool/method/url)
- field-level path changes
