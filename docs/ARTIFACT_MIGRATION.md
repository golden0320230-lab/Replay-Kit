# Artifact Migration

ReplayPack supports deterministic migration from legacy artifact schema `0.9` to current schema `1.0`.

## Supported transitions

- `0.9` -> `1.0` (legacy upgrade path)
- `1.x` -> `1.0` (canonical rewrite to current minor)

Any other source major version is rejected.

## CLI usage

```bash
replaykit migrate runs/legacy-0.9.rpk --out runs/migrated.rpk --json
```

Example JSON summary fields:

- `status` (`pass` or `error`)
- `source_version`
- `target_version`
- `migration_status` (`migrated` or `already_current`)
- `preserved_step_hashes`
- `recomputed_step_hashes`

## Hash behavior

Migration recomputes step hashes from canonical step content.  
If a source step hash already matches canonical content, it is counted as `preserved_step_hashes`; otherwise it is counted as `recomputed_step_hashes`.

This keeps migrated artifacts deterministic and replay-compatible.

## Legacy `0.9` mapping

- `payload.run.env_fingerprint` -> `payload.run.environment_fingerprint`
- `payload.run.runtime` -> `payload.run.runtime_versions`
- `step.request` -> `step.input`
- `step.response` -> `step.output`
- `step.step_hash` -> `step.hash` (validated against canonical step hash)

## Failure behavior

Migration fails with non-zero exit code for:

- unsupported source versions
- checksum mismatch
- malformed legacy payload shape
