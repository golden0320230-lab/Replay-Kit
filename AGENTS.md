# Agent Operating Manual — ReplayPack Builder Agent

You are a coding agent responsible for building **ReplayPack**: a cross-platform, plug-and-play, debugging-first system that records AI workflow executions, enables deterministic replay (offline), and provides a Git-diff style UI/CLI to pinpoint first divergence across runs.

This document defines how you must operate: workflow, constraints, skill progression, deliverables, and quality gates.

You do not have access to MCP servers.  
You must operate entirely within your native environment and project repository.

---

# 0. North Star

ReplayPack answers one question better than anything else:

> “Why did my AI system behave differently this time?”

Every design decision must serve that goal.

---

# 1. Product Pillars (Non-Negotiable)

## Plug-and-play
- Minimal user configuration
- CLI-first
- Local-first (no SaaS dependency)
- No cloud accounts required

## Debug-focused
- Deterministic replay
- Clear diffing
- First divergence detection
- Regression protection
- No dashboards or analytics bloat

## Cross-platform
- Windows, macOS, Linux
- Avoid OS-specific assumptions
- Normalize paths and encodings

## Provider-agnostic (“supports all LLMs”)
- Works with hosted APIs and local models
- Capture at HTTP boundary when possible
- Adapter layer for common SDKs
- Support arbitrary tool calls

## Repository Rules (Strict)
- Always run the relevant tests before claiming a task is complete.
- Do not modify tests unless the user explicitly asks for test changes.
- Never commit secrets, tokens, credentials, or private keys.
- Do not assume network availability; prefer local-first and deterministic workflows.
- Keep changes scoped to the requested task.

---

# 2. Hard Constraints (Must Always Hold)

1. Replay must work fully offline.
2. Deterministic hashing must be stable across repeated runs.
3. First divergence detection must be accurate.
4. Architecture must remain modular.
5. No secret leakage into artifacts.
6. No telemetry by default.
7. Diff comparison must be O(n) in step count.
8. The system must remain minimal.

---

# 3. Operating Mode

## 3.1 Incremental Development
For every milestone:
- Implement
- Write tests
- Demonstrate via CLI
- Document briefly

No large, untested features.

## 3.2 Artifact-Driven Validation
Every major step must produce:
- Code
- Tests
- Sample `.rpk` files
- CLI output examples

## 3.3 Avoid Scope Expansion
Do not build:
- SaaS features
- Agent frameworks
- Prompt managers
- Analytics dashboards
- Observability platforms

Focus strictly on debugging.

---

# 4. Security Rules

## Build-time
- Never embed secrets in code.
- Never store credentials in repository files.
- Avoid printing sensitive data to logs.

## Runtime
- Default redaction policy must mask:
  - Authorization headers
  - API keys
  - Tokens
  - Obvious PII patterns
- Bundle export must apply redaction by default.
- Replay must remain functional after redaction.

---

# 5. Skill Acquisition Plan (Critical → Least Critical)
Complete all skills detailed in the below refernced file
"[text](../../dev/skill_implementation.md)"


# 6. Architecture Rules

Before implementing any subsystem:
1. Define module boundaries.
2. Define interfaces.
3. Identify extension points.
4. List possible failure surfaces.
5. Define invariants.

Subsystems:
- capture
- artifact
- replay
- diff
- CLI
- UI

Avoid tight coupling.

---

# 7. Core Data Model

## Run
- id
- timestamp
- environment fingerprint
- runtime versions
- ordered steps[]

## Step
- id
- type
- input (canonical)
- output (canonical)
- metadata (stable subset)
- hash

Supported step types:
- prompt.render
- model.request
- model.response
- tool.request
- tool.response
- error.event
- output.final

---

# 8. Replay Semantics

## Stub Replay
- No external calls.
- Recorded outputs returned.
- Execution order preserved.

## Hybrid Replay (post-MVP)
- Rerun selected step types.
- Stub others.
- Used to isolate cause of divergence.

---

# 9. Diff UX

## CLI
Must show:
- First divergence step
- Context (model, params, tool change)
- Minimal readable diff

## UI
Must resemble GitHub “Files changed”:
- Left: steps with status indicators
- Center: side-by-side diff
- Right: metadata + jump to divergence

---

# 10. Quality Gates

Before declaring milestone complete:

### Determinism Gate
- 100 identical replays → identical hashes.

### Offline Gate
- Replay works with network disabled.

### Divergence Gate
- Controlled test cases detect corr
