# ReplayKit `.rpk` Artifact Format (v1)

## Goals

- Deterministic serialization
- Local/offline replay portability
- Clear schema validation failures
- Versioned evolution without silent breakage

## Envelope

Each `.rpk` artifact is a JSON object with this envelope:

```json
{
  "version": "1.0",
  "metadata": {
    "run_id": "run-123",
    "created_at": "2026-02-21T14:00:00Z"
  },
  "payload": {
    "run": {
      "id": "run-123",
      "timestamp": "2026-02-21T14:00:00Z",
      "environment_fingerprint": {},
      "runtime_versions": {},
      "steps": []
    }
  },
  "checksum": "sha256:<hex>"
}
```

## Run Object

Required fields:

- `id`
- `timestamp`
- `environment_fingerprint`
- `runtime_versions`
- `steps`

## Step Object

Required fields:

- `id`
- `type`
- `input`
- `output`
- `metadata`
- `hash`

Supported `type` values:

- `prompt.render`
- `model.request`
- `model.response`
- `tool.request`
- `tool.response`
- `error.event`
- `output.final`

## Canonicalization Rules

- Map keys are sorted.
- Unknown fields are preserved unless explicitly removed.
- String line endings are normalized to `\n`.
- Path-like fields are normalized to POSIX-style separators.
- Timestamp-like fields are normalized to UTC ISO-8601 when timezone info is present.
- Volatile metadata keys (for hashing) are removed using an explicit denylist.

## Step Hashing

Step hash input scope:

- `type`
- canonical `input`
- canonical `output`
- canonical `metadata` with volatile fields removed

Algorithm:

- `sha256`
- encoded as `sha256:<64-lowercase-hex>`

## Artifact Checksum

Artifact checksum is `sha256` of canonical JSON containing only:

- `version`
- `metadata`
- `payload`

The `checksum` field is excluded from checksum input.

## Version Compatibility

- Current supported major: `1.x`
- Reader behavior:
  - same major: accepted
  - different major: fail fast with explicit error

This allows additive minor evolution inside major `1` while preventing silent interpretation errors across major schema breaks.
