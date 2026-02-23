# Security Policy

## Reporting a Vulnerability

Please do not open public issues for potential security problems.

Use one of the following private paths:

- Open a private GitHub Security Advisory for this repository.
- Contact maintainers directly and include:
  - affected versions/commit
  - reproduction steps
  - impact and suggested mitigation (if known)

We will acknowledge reports as quickly as possible and coordinate a fix/release path.

## Secret Handling

- Do not commit secrets, tokens, credentials, or private keys.
- Do not commit artifacts that contain unredacted secrets.
- Rotate any leaked secrets immediately.

## Redaction Guidance

ReplayKit is designed for safe-by-default redaction. Contributors must preserve:

- default masking of secret-bearing headers/fields
- no plain-text secret values in CLI logs
- replay functionality after redaction is applied

## Supported Versions

Security fixes are prioritized for:

- the latest release tag
- `main` branch

Older versions may receive fixes at maintainer discretion.
