# Artifact Signing and Verification

## Purpose

Artifact signing adds tamper-evident integrity for `.rpk` and bundle files shared across teams.

ReplayKit uses:

- checksum: deterministic `sha256` over `version` + `metadata` + `payload`
- signature: optional HMAC (`hmac-sha256`) over `version` + `metadata` + `payload` + `checksum`

## Key Handling Model

- Signing and verification keys are never written to artifacts.
- Use environment variables or CLI flags:
  - `REPLAYKIT_SIGNING_KEY` (required for signing and for signature verification)
  - `REPLAYKIT_SIGNING_KEY_ID` (optional key identifier, default `default`)
- Recommended practice:
  - set keys in CI secret storage
  - avoid committing keys to repo or scripts

## CLI Usage

Sign during record:

```bash
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit record --sign --out runs/signed-recording.rpk
```

Sign during bundle:

```bash
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit bundle runs/source.rpk --out runs/signed.bundle --sign
```

Verify signature (default requires signature):

```bash
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit verify runs/signed-recording.rpk
```

Allow unsigned artifacts:

```bash
replaykit verify runs/unsigned.rpk --allow-unsigned
```

Machine-readable verification output:

```bash
REPLAYKIT_SIGNING_KEY="dev-signing-key" replaykit verify runs/signed-recording.rpk --json
```

## Verification Semantics

- `exit 0`:
  - signature verified, or
  - artifact unsigned and `--allow-unsigned` is set
- `exit 1`:
  - checksum invalid
  - signature missing (when required)
  - signature algorithm unsupported
  - signature key missing
  - signature mismatch
