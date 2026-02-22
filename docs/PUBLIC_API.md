# ReplayKit Public API Contract (Issue #1)

## Supported Import Path

Use:

```python
import replaykit
```

This is the stable, semver-governed API surface.

## Public Functions

```python
replaykit.record(path, *, mode="stub", redaction=True)
replaykit.replay(path, *, out, mode="stub", seed=0, fixed_clock="2026-01-01T00:00:00Z")
replaykit.diff(left, right, *, first_only=False, max_changes_per_step=32)
replaykit.assert_run(baseline, candidate, *, strict=False, max_changes_per_step=32)
replaykit.bundle(path, *, out, redaction_profile="default")
```

## Stability Policy

- Public symbols exported by `replaykit.__all__` are considered stable for `v1.x`.
- Breaking changes to public function signatures require a major version bump.
- Additive keyword-only parameters are allowed in minor releases.
- Deprecated APIs must emit warnings for at least one minor release before removal.

## Notes

- Current `record(...)` implementation records ReplayKit's deterministic demo flow.
- `assert_run(..., strict=True)` is reserved and currently raises `NotImplementedError`.
- Internal modules under `replaypack.*` are implementation details and may change.
