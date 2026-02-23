# ReplayKit Release Notes: Provider Capture + Target Recording

## Highlights

- Added first-class target command recording flow:
  - `replaykit record --out runs/app.rpk -- python examples/apps/minimal_app.py`
- Added provider-shaped capture workflow for local deterministic model debugging.
- Expanded CI golden-path checks for record/replay/assert/diff invariants.

## Why This Release

This release hardens ReplayKit's production debugging path around two core use
cases:

1. Record real target app behavior without modifying application code.
2. Capture provider request/response shape in deterministic local workflows.

## Verification Commands

```bash
python3 -m pytest -q
replaykit record --out runs/release-target.rpk -- python examples/apps/minimal_app.py
replaykit replay runs/release-target.rpk --out runs/release-target-replay.rpk
replaykit assert runs/release-target-replay.rpk --candidate runs/release-target-replay.rpk --json
```

## Notes

- Replay remains offline deterministic.
- No provider secrets should be committed to artifacts or repository files.
