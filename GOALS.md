# ReplayKit Goals and Task Tracker

## Project Goal

Build a plug-and-play, cross-platform debugging system for AI workflows that provides deterministic replay and first-divergence diffs.

## Milestones

- [x] M0: Repository bootstrap and scaffolding
- [x] M1: Deterministic `.rpk` artifact schema + canonicalization
- [ ] M2: Capture engine (model/tool/http boundaries)
- [ ] M3: Offline stub replay
- [ ] M4: O(n) diff engine + first divergence detection
- [ ] M5: Security redaction defaults and bundle export
- [ ] M6: CLI hardening + CI regression assertions
- [ ] M7: Local diff UI

## Current Sprint Tasks

- [x] Define v1 artifact schema document
- [x] Implement canonical JSON serializer for stable hashing
- [x] Add `Run` and `Step` core models
- [x] Implement baseline hash function for steps
- [x] Build `replaykit record` command stub
- [x] Build `replaykit replay` command stub
- [x] Add deterministic replay fixture examples

## Task Log

- 2026-02-21: Initialized repository docs and package scaffold.
- 2026-02-21: Completed M1 artifact schema, canonicalization, hashing, and validation tests.
