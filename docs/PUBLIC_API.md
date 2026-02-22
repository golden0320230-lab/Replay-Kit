# ReplayKit Public API Contract (v1.x)

## Supported Import Path

Use:

```python
import replaykit
```

This is the stable, semver-governed API surface.

## Stable Module Surface

- `replaykit` is the only stable top-level module for library users.
- `replaykit.__all__` is the source of truth for exported public symbols.
- Modules under `replaypack.*` are internal implementation details.

## Public Symbols (Current v1.x)

```python
replaykit.__all__ == [
    "__version__",
    "ReplayMode",
    "CaptureInterceptor",
    "AssertionResult",
    "RunDiffResult",
    "SnapshotWorkflowResult",
    "tool",
    "record",
    "replay",
    "diff",
    "assert_run",
    "bundle",
    "snapshot_assert",
]
```

## Public Functions

```python
replaykit.record(path, *, mode="stub", redaction=True)
with replaykit.record(path, intercept=("requests", "httpx")):
    ...
replaykit.replay(path, *, out, mode="stub", seed=0, fixed_clock="2026-01-01T00:00:00Z", rerun_from=None, rerun_step_types=(), rerun_step_ids=())
replaykit.diff(left, right, *, first_only=False, max_changes_per_step=32, redaction_policy=None)
replaykit.assert_run(baseline, candidate, *, strict=False, max_changes_per_step=32)
replaykit.bundle(path, *, out, redaction_profile="default", redaction_policy=None)
replaykit.snapshot_assert(name, candidate, *, snapshots_dir="snapshots", update=False, strict=False, max_changes_per_step=32)
```

## Stability Policy

- Public symbols exported by `replaykit.__all__` are considered stable for `v1.x`.
- Breaking changes to public function signatures require a major version bump.
- Additive keyword-only parameters are allowed in minor releases.
- Deprecated APIs must emit warnings for at least one minor release before removal.
- Public API tests in `tests/test_public_api_contract.py` must be updated in the same change as any public API change.

## Notes

- `replaykit.record(...)` currently records ReplayKit's deterministic demo flow when
  used as a direct function call.
- CLI record target mode (`replaykit record -- <command>`) executes arbitrary script
  or module targets and captures boundary events around that execution.
- `record(..., intercept=(...))` returns a context manager for library-first capture.
- Current automatic wrapper interception scope is `requests` and `httpx`; provider SDKs
  outside installed adapters are not intercepted by default.
- `assert_run(..., strict=True)` enables stricter drift gates and fails on:
  - run `environment_fingerprint` mismatch
  - run `runtime_versions` mismatch
  - per-step `metadata` drift (including volatile metadata fields)
- Internal modules under `replaypack.*` are implementation details and may change without deprecation guarantees.
