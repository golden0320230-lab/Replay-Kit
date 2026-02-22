# CI Regression Assertion and Parity Checks

## Purpose

`replaykit assert` provides CI-safe pass/fail semantics for behavior regression checks.

- exit `0`: baseline and candidate are identical
- exit `1`: divergence detected or input error

CI additionally enforces deterministic replay hash parity against a checked-in
expected digest baseline (`ci/expected_hash_parity.json`).

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

Output hardening flags:

```bash
replaykit --quiet assert baseline.rpk --candidate candidate.rpk
replaykit --no-color assert baseline.rpk --candidate candidate.rpk --json
replaykit --stable-json assert baseline.rpk --candidate candidate.rpk --json
```

Determinism guardrails:

```bash
replaykit assert baseline.rpk --candidate candidate.rpk --nondeterminism warn --json
replaykit assert baseline.rpk --candidate candidate.rpk --nondeterminism fail --json
```

## Local Reproduction (matches CI)

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
python3 -c "from pathlib import Path; Path('runs').mkdir(parents=True, exist_ok=True)"
python3 -m replaypack assert examples/runs/m2_capture_boundaries.rpk --candidate examples/runs/m2_capture_boundaries.rpk --json > runs/ci-assert.json
python3 -m replaypack.ci_parity --source examples/runs/m2_capture_boundaries.rpk --out-dir runs/parity --expected ci/expected_hash_parity.json --json > runs/parity/ci-hash-parity.json
```

## CI Matrix

- `ubuntu-latest`
- `macos-latest`
- `windows-latest`

## CI Artifact Paths

- `runs/ci-assert.json` assertion output
- `runs/parity/parity-replay.rpk` deterministic replay artifact used for parity check
- `runs/parity/hash-parity-summary.json` computed parity summary
- `runs/parity/ci-hash-parity.json` parity check result payload
- `runs/` directory uploaded per-OS as workflow artifact (`replay-artifacts-<os>`)

## Failure Diagnostics

On divergence, output includes:

- first divergence step index
- left/right step ids and types
- high-signal context (model/tool/method/url)
- field-level path changes
