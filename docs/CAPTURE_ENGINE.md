# ReplayKit Capture Engine (M2)

## Scope

M2 implements deterministic capture boundaries for:

- model calls
- tool calls
- HTTP calls

The capture API emits structured `Step` records through a run-scoped `CaptureContext`.

## Public API

- `capture_run(...)` context manager
- `capture_model_call(...)`
- `capture_tool_call(...)`
- `@tool(...)` decorator
- `capture_http_call(...)`
- `InterceptionPolicy` (allow/deny controls)
- `RedactionPolicy` (security-first masking)
- `build_demo_run(...)` deterministic demo workflow

CLI demo:

```bash
replaykit record --out runs/demo-recording.rpk
```

## Boundary Policy

`InterceptionPolicy` supports explicit control over boundary execution:

- `allow_model`
- `allow_tool`
- `allow_http`
- `allowed_hosts`
- `blocked_hosts`
- `capture_http_bodies`

Denied boundaries raise `BoundaryPolicyError` and are also recorded as `error.event` steps for debugging.

## Redaction Defaults

Capture data is redacted before step persistence.

Default masking includes:

- `Authorization`
- `api_key` / `token` / `password` / `secret`
- cookies
- common secret-like tokens and PII-like patterns

HTTP bodies are omitted by default (`capture_http_bodies=False`) to reduce leakage risk in artifacts.

## Determinism Notes

- step IDs are monotonic (`step-000001`, ...)
- step hashes are computed deterministically with volatile metadata excluded
- concurrent `record_step` writes are serialized for stable, gap-free step IDs

## Context Scope Semantics

- `capture_run(...)` uses stack semantics for nesting:
  - entering inner scope activates inner context
  - exiting inner scope restores previous outer context
- Async tasks can safely run independent capture scopes without cross-run leakage.
- New OS threads do not inherit active capture context automatically.
  - For shared threaded capture, pass `context=...` explicitly to capture wrappers.

## Current Limits

- M2 provides wrapper-based capture boundaries.
- Framework/SDK monkeypatch adapters are planned in later milestones.
- Replay semantics are out of scope for M2 and begin in M3.
