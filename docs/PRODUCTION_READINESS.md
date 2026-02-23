# Production Readiness Standard

This document defines the minimum bar for ReplayKit changes to be considered production ready.

## Definition of Done (DoD)

A change is done only when all of the following are true:

- Tests pass locally.
- Golden path CLI flows are runnable and deterministic.
- Public API impact is reviewed and documented.
- Artifact compatibility is preserved or migration is provided.
- Security and redaction requirements are met.
- Release metadata and notes are prepared when behavior changes.

## Mandatory Checks

Run these checks before merge:

```bash
python3 -m pytest -q
mkdir -p runs/golden runs/parity
python3 -m replaypack record --out runs/golden/target.rpk -- python3 examples/apps/minimal_app.py
python3 -m replaypack replay runs/golden/target.rpk --out runs/golden/replay-a.rpk --seed 7 --fixed-clock 2026-02-22T00:00:00Z
python3 -m replaypack replay runs/golden/target.rpk --out runs/golden/replay-b.rpk --seed 7 --fixed-clock 2026-02-22T00:00:00Z
python3 -m replaypack assert runs/golden/replay-a.rpk --candidate runs/golden/replay-b.rpk --json
python3 -m replaypack diff runs/golden/replay-a.rpk runs/golden/replay-a.rpk --json
python3 -m replaypack.ci_parity --source examples/runs/m2_capture_boundaries.rpk --out-dir runs/parity --expected ci/expected_hash_parity.json --json
```

## Determinism Guardrails

All replay and comparison paths must remain deterministic across repeated runs:

- Always use stable canonicalization and step ordering.
- Seeded flows must produce identical artifacts when seed and inputs are identical.
- Fixed-clock runs must not depend on wall-clock time.
- Path handling must remain cross-platform and normalized.
- Float normalization must avoid platform-dependent formatting drift.
- Diff and first-divergence detection must remain stable for identical inputs.

## Public API Contract

If a change touches user-facing Python or CLI behavior:

- Update and validate `docs/PUBLIC_API.md`.
- Keep backward compatibility unless explicitly planning a breaking major release.
- Ensure tests cover changed API paths and expected exit-code behavior.

## Artifact Schema and Migration Rules

For artifact changes:

- Preserve current schema compatibility when possible.
- If schema changes are required, update schema docs and migration path.
- Keep deterministic hashing behavior stable for semantically identical runs.
- Validate read/write compatibility via existing artifact tests.

## Security and Privacy Rules

Security expectations for every change:

- Never commit secrets, tokens, credentials, or private keys.
- Keep redaction safe-by-default for secret-bearing fields/payloads.
- Do not log raw sensitive values in CLI output or artifacts.
- Ensure replay remains functional after redaction is applied.

## Release Readiness

Before release:

- Version sync must hold:
  - `pyproject.toml` `[project].version`
  - `replaykit/__init__.py` `__version__`
- `CHANGELOG.md` must be updated from `[Unreleased]` into a dated release section.
- Release/tag workflow in `docs/RELEASES.md` must be followed.

