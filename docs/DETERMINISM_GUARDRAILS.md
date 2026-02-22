# Determinism Guardrails (Issue #7)

## Purpose

Guardrails detect indicators of nondeterministic behavior that can cause replay/assert drift:

- unseeded randomness
- unstable time usage

Guardrails are available in CLI replay/assert workflows.

## Modes

- `off`: disabled (default)
- `warn`: report findings, continue command
- `fail`: report findings and return non-zero

## Replay Usage

```bash
replaykit replay runs/source.rpk --nondeterminism warn
replaykit replay runs/source.rpk --nondeterminism fail --json
```

In `fail` mode, replay exits `1` when indicators are detected.

## Assert Usage

```bash
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --nondeterminism warn --json
replaykit assert runs/baseline.rpk --candidate runs/candidate.rpk --nondeterminism fail --json
```

In `fail` mode, assert exits `1` when indicators are detected even if behavior diff is otherwise clean.

## JSON Output

Replay and assert JSON output include:

```json
{
  "nondeterminism": {
    "mode": "warn",
    "status": "warn",
    "count": 2,
    "findings": [
      {
        "kind": "random_unseeded",
        "path": "/runtime_versions/uses_random",
        "message": "...",
        "source": "source"
      }
    ]
  }
}
```

`status` values:

- `off`
- `clear`
- `warn`
- `fail`
