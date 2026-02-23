# Passive Mode Release Checklist

This checklist defines release-blocking gates for practical passive mode.

## Scope

Applies to passive listener operation where target apps and coding agents run
independently and route traffic through ReplayKit.

Golden artifact path:

- `examples/runs/passive_listener_golden_path.rpk`

## Required Gates (Release Blocking)

1. Cross-platform CI green:
   - GitHub Actions `ci` workflow passes on `ubuntu-latest`, `macos-latest`,
     and `windows-latest`.
2. No secret leakage in persisted outputs:
   - Redaction tests pass.
   - Passive artifacts and logs avoid raw keys/tokens/password values.
3. Deterministic replay parity:
   - Replay of passive golden artifact is stable with fixed seed/clock.
   - `assert` reports no divergence between repeated replays.
4. Golden passive artifact validity:
   - `examples/runs/passive_listener_golden_path.rpk` is readable and replayable
     in stub mode.

## Verification Commands

Run from repository root.

```bash
python3 -m pytest -q
python3 -m replaypack replay examples/runs/passive_listener_golden_path.rpk --out runs/golden/passive-golden-replay-a.rpk --seed 23 --fixed-clock 2026-02-23T00:00:00Z
python3 -m replaypack replay examples/runs/passive_listener_golden_path.rpk --out runs/golden/passive-golden-replay-b.rpk --seed 23 --fixed-clock 2026-02-23T00:00:00Z
python3 -m replaypack assert runs/golden/passive-golden-replay-a.rpk --candidate runs/golden/passive-golden-replay-b.rpk --json
```

## Sign-Off

Before tagging a release that includes passive mode changes:

1. Attach the latest successful CI run URL.
2. Confirm replay parity command output is `status=pass`.
3. Confirm redaction/security tests are green.
4. Confirm artifact path and checksum for
   `examples/runs/passive_listener_golden_path.rpk`.

