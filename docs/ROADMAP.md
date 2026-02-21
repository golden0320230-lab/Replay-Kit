# ReplayKit Production Roadmap (Post-M7)

## Current Baseline

Completed milestones:

- M0: Repository bootstrap
- M1: Deterministic artifact schema + canonicalization
- M2: Capture boundaries
- M3: Offline stub replay
- M4: O(n) diff + first divergence
- M5: Bundle export + redaction profile
- M6: CI-oriented assert command
- M7: Local diff UI

This roadmap tracks production hardening beyond the current baseline.

## Phase P1 (Weeks 1-3): Stable API + Interception

- Define and freeze stable public API surface
- Add strict-mode assertion semantics
- Harden capture context (sync/async/thread safety)
- Add drop-in interception adapters for `httpx`, `requests`, and OpenAI/LLM boundary

Issue map:
- #1 Define and freeze stable public API surface
- #2 Implement strict mode assertion semantics
- #3 Harden capture context for sync/async/thread safety
- #4 Add drop-in interception adapters for httpx, requests, and OpenAI/LLM

## Phase P2 (Weeks 3-6): Determinism and Artifact Trust

- Publish explicit on-disk schema artifact and compatibility docs
- Add artifact signing + verification
- Add determinism guardrails for random/time sources

Issue map:
- #5 Publish versioned schema file and compatibility policy
- #6 Add artifact signing and verification
- #7 Implement determinism guardrails for random/time usage

## Phase P3 (Weeks 6-8): Replay Depth + CI Guarantees

- Implement hybrid replay mode
- Implement live-compare mode
- Add cross-platform CI matrix and hash parity checks

Issue map:
- #8 Implement hybrid replay mode
- #9 Implement live-compare mode
- #10 Add cross-platform CI matrix and hash parity checks

## Phase P4 (Weeks 8-10): Test Workflow + CLI Hardening

- Add snapshot testing workflow for pytest and CLI
- Harden CLI output options (`--quiet`, `--no-color`, stable JSON)

Issue map:
- #11 Add snapshot testing workflow for pytest and CLI
- #12 Harden CLI output modes (`--quiet`, `--no-color`, stable JSON)

## Phase P5 (Weeks 10-12): Performance + Extensibility

- Add performance benchmark + slowdown assertion gate
- Add custom redaction rules and policy plugin hooks
- Implement plugin system for capture/replay/diff lifecycle hooks

Issue map:
- #13 Add performance benchmarking and slowdown assertion gates
- #14 Add custom redaction rules and policy hooks
- #15 Implement plugin system for capture/replay/diff lifecycle

## Phase P6 (Weeks 12+): Long-Term Stability

- Implement artifact migration CLI for schema upgrades
- Add fuzz testing for canonicalization/diff/parser
- Upgrade local UI with advanced diff UX (changed-only, collapsible JSON, copy path)

Issue map:
- #16 Implement artifact migration CLI and upgrade path
- #17 Add fuzz testing for canonicalization, diff, and parser
- #18 Upgrade local UI with advanced diff UX

## Execution Rules

- Keep replay fully offline-compatible
- Preserve deterministic hashing invariants
- Maintain O(n) step comparison guarantees
- Keep default security redaction enabled for shared artifacts
- Require tests + CI updates for every roadmap issue
