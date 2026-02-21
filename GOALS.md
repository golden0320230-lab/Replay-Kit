# ReplayKit Goals and Task Tracker

## Project Goal

Build a plug-and-play, cross-platform debugging system for AI workflows that provides deterministic replay and first-divergence diffs.

## Milestones

- [x] M0: Repository bootstrap and scaffolding
- [x] M1: Deterministic `.rpk` artifact schema + canonicalization
- [x] M2: Capture engine (model/tool/http boundaries)
- [x] M3: Offline stub replay
- [x] M4: O(n) diff engine + first divergence detection
- [x] M5: Security redaction defaults and bundle export
- [ ] M6: CLI hardening + CI regression assertions
- [ ] M7: Local diff UI

## Current Sprint Tasks

- [x] Implement `CaptureContext` run-scoped recorder
- [x] Add model/tool/HTTP interception wrappers
- [x] Add policy-based allow/deny for boundaries
- [x] Add default security redaction for captured payloads
- [x] Add capture engine tests and deterministic demo CLI recording
- [x] Implement offline stub replay engine (`M3`)
- [x] Add replay fixtures for deterministic offline execution (`M3`)
- [x] Implement O(n) first-divergence diff engine (`M4`)
- [x] Add CLI diff output with first divergence context (`M4`)
- [x] Implement bundle export with default redaction profiles (`M5`)
- [x] Add replay-safe bundle round-trip tests (`M5`)
- [ ] Implement `assert` command behavior-regression exit semantics (`M6`)
- [ ] Add CI-oriented machine-readable assertion output (`M6`)

## Task Log

- 2026-02-21: Initialized repository docs and package scaffold.
- 2026-02-21: Completed M1 artifact schema, canonicalization, hashing, and validation tests.
- 2026-02-21: Completed M2 capture engine boundaries with interception policy, redaction defaults, tests, and CLI demo recording.
- 2026-02-21: Completed M3 offline stub replay engine with deterministic seed/clock controls and replay CLI.
- 2026-02-21: Completed M4 O(n) diff engine, first-divergence detection, and CLI diff modes.
- 2026-02-21: Completed M5 bundle export with default redaction profile and replay-safe bundle validation.
