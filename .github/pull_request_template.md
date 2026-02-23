## Summary

- What problem does this PR solve?
- What changed at a high level?

## Change Type

- [ ] Bug fix
- [ ] Feature (non-breaking)
- [ ] Breaking change
- [ ] Docs only
- [ ] Test only
- [ ] CI/Build/Chore

## Risk & Rollback

- Risk level: `low` / `medium` / `high`
- Failure surface:
- Rollback plan:

## How Tested

Run and paste results:

- [ ] `python -m pytest -q`
- [ ] `mkdir -p runs/golden`
- [ ] `python -m replaypack record --out runs/golden/target.rpk -- python examples/apps/minimal_app.py`
- [ ] `python -m replaypack replay runs/golden/target.rpk --out runs/golden/replay-a.rpk --seed 7 --fixed-clock 2026-02-22T00:00:00Z`
- [ ] `python -m replaypack replay runs/golden/target.rpk --out runs/golden/replay-b.rpk --seed 7 --fixed-clock 2026-02-22T00:00:00Z`
- [ ] `python -m replaypack assert runs/golden/replay-a.rpk --candidate runs/golden/replay-b.rpk --json`
- [ ] `python -m replaypack diff runs/golden/replay-a.rpk runs/golden/replay-a.rpk --json`
- [ ] `mkdir -p runs/parity`
- [ ] `python -m replaypack.ci_parity --source examples/runs/m2_capture_boundaries.rpk --out-dir runs/parity --expected ci/expected_hash_parity.json --json`

## Production Readiness Checklist

- [ ] Determinism preserved (seed/clock/order/path normalization remains stable).
- [ ] Public API impact reviewed (`docs/PUBLIC_API.md` updated if needed).
- [ ] Artifact schema compatibility preserved, or migration path documented.
- [ ] Security/redaction reviewed (no secrets in logs/artifacts; redaction still safe-by-default).
- [ ] Docs/examples updated and commands are runnable as written.

## Release PR Checklist

- [ ] Version updated consistently:
  - [ ] `pyproject.toml` `[project].version`
  - [ ] `replaykit/__init__.py` `__version__`
- [ ] `CHANGELOG.md` updated:
  - [ ] `[Unreleased]` entries moved into release section
  - [ ] release date added
- [ ] Release docs updated if behavior changed (`docs/RELEASES.md` or release notes file).
