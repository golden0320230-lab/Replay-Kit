# Changelog

All notable changes to this project are documented in this file.

The format follows Keep a Changelog and Semantic Versioning.

## [Unreleased]

### Added

- Release hardening updates:
  - `replaykit --version` now validated against package runtime version in tests.
  - README install section now documents both `pip install -e .` and
    `python3 -m pip install -e \".[dev]\"`.
  - Release process docs continue to use GitHub release notes from `CHANGELOG.md`.
- Provider-capture + target-recording release notes template added:
  - `docs/release-notes-provider-capture-target-recording.md`.
  - `docs/RELEASES.md` now includes explicit command examples for publishing notes.

### Changed

- _None yet._

### Fixed

- _None yet._

## [0.1.0] - 2026-02-22

### Added

- Deterministic artifact format with schema validation and migration support.
- Capture boundaries for model/tool/http events with redaction.
- Offline replay (stub + hybrid) and first-divergence diffing.
- CLI commands for record/replay/diff/assert/bundle/verify/snapshot/benchmark/migrate/ui.
- Local diff UI and CI parity/assert integration.

### Security

- Redaction defaults for common secret-bearing fields and signature verification workflow.
