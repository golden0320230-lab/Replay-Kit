# ReplayKit Bundle Export (M5)

## Scope

M5 adds bundle export with redaction-by-default for safe sharing and repro handoff.

## Bundle Semantics

- Bundle export reads an artifact and writes a new artifact-like bundle file.
- Redaction is applied before writing persisted output.
- Bundle artifacts remain replay-compatible with `replaykit replay`.

## Redaction Profiles

Supported profiles:

- `default`: security-first masking enabled
- `none`: redaction disabled

Default profile is `default`.

## Default Redaction Behavior

Masks sensitive fields and values, including:

- authorization headers
- API keys and token-like fields
- cookies
- common key/token patterns
- email-like values

## CLI Usage

Default redaction:

```bash
replaykit bundle examples/runs/m2_capture_boundaries.rpk --out runs/incident.bundle
```

No redaction:

```bash
replaykit bundle examples/runs/m2_capture_boundaries.rpk --out runs/raw.bundle --redact none
```

Machine-readable output:

```bash
replaykit bundle examples/runs/m2_capture_boundaries.rpk --json
```

## Replay Compatibility

Bundle output is validated by the same artifact schema and checksum flow.
It can be replayed offline using the existing replay command.
