# ReplayKit Artifact Schemas

Stable schema path format:

- `schemas/rpk-<major>.<minor>.schema.json`

Current published schema:

- `schemas/rpk-1.0.schema.json`

Compatibility contract:

- Reader accepts artifacts on major `1` (`1.x`).
- Minor versions are additive and backward-compatible for readers within major `1`.
- New major versions require explicit reader support and schema publication.

Migration expectation:

- When introducing a breaking schema change, publish a new major schema file and a migration path.
- Migration tooling is tracked separately in roadmap Issue #16.
