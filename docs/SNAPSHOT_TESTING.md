# Snapshot Testing Workflow

## Purpose

Snapshot testing lets you keep a baseline `.rpk` artifact per workflow and assert
new candidate runs against it in CI or local tests.

## CLI Workflow

Create or update a baseline snapshot:

```bash
replaykit snapshot my-flow \
  --candidate runs/candidate.rpk \
  --snapshots-dir snapshots \
  --update
```

Assert candidate against existing snapshot baseline:

```bash
replaykit snapshot my-flow \
  --candidate runs/candidate.rpk \
  --snapshots-dir snapshots \
  --json
```

Strict assertion mode:

```bash
replaykit snapshot my-flow \
  --candidate runs/candidate.rpk \
  --snapshots-dir snapshots \
  --strict --json
```

## Pytest Helper API

```python
import replaykit

def test_flow_snapshot(tmp_path):
    candidate_path = tmp_path / "candidate.rpk"
    # produce candidate artifact before snapshot_assert(...)

    replaykit.snapshot_assert(
        "my-flow",
        candidate_path,
        snapshots_dir=tmp_path / "snapshots",
        update=True,  # baseline bootstrap/update
    )

    result = replaykit.snapshot_assert(
        "my-flow",
        candidate_path,
        snapshots_dir=tmp_path / "snapshots",
    )
    assert result.status == "pass"
```

## CI Behavior

- `status=updated|pass` exits `0`
- `status=fail|error` exits `1`
- JSON output includes machine-parseable `first_divergence` and nested `assertion`
  payload for regression diagnostics
