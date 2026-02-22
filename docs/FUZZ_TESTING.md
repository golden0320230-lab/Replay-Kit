# Fuzz Testing Strategy

ReplayPack includes deterministic fuzz smoke tests focused on robustness:

- canonicalization (`replaypack.core.canonical`)
- artifact parsing (`replaypack.artifact.read_artifact_envelope`)
- diff engine (`replaypack.diff.diff_runs`)

## Goals

- prevent unexpected crashes on malformed/unexpected inputs
- preserve deterministic behavior under randomized nested payloads
- keep a reproducible corpus for regressions

## Test entrypoint

Run only fuzz smoke tests:

```bash
python3 -m pytest -q tests/test_fuzz_stability.py
```

Run full suite:

```bash
python3 -m pytest -q
```

## Corpus and repro retention

Seed corpus lives under `tests/fuzz_corpus/`:

- `canonical/` canonicalization seed payloads
- `parser/` malformed artifact payloads
- `diff/` seed run-pair payloads

When fuzz detects an unexpected exception, tests persist a reproduction JSON under:

- `tests/fuzz_corpus/repro/`

Keep meaningful repro files in git as permanent regression fixtures.

## Determinism

Fuzz tests use fixed seeds and bounded recursion depth to remain deterministic and CI-friendly while still covering varied nested structures.
