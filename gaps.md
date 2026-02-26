# Practical Passive Mode Gap -> GitHub Issue Drafts

Use this file to create GitHub issues for practical passive mode, where an app/agent runs on its own and traffic is routed through ReplayKit.

## Epic

**Title:** Practical Passive Mode (App Runs Independently, ReplayKit Captures in Parallel)

**Outcome:**
- External apps/agents run normally without ReplayKit wrappers.
- ReplayKit passively captures provider and agent traffic.
- Captured artifacts replay offline deterministically.
- No secrets leak into artifacts/logs.
- CI is green on Linux/macOS/Windows.

---

## Issue GAP-PM-01: Define Passive Capture Contract

**Type:** design/architecture  
**Priority:** P0  
**Depends on:** none

### Objective
Define the passive contract: supported providers/endpoints, streaming rules, required metadata, and failure semantics.

### Scope
- Providers: OpenAI, Anthropic, Gemini.
- Endpoint matrix per provider (chat/responses/messages/generate variants actually supported).
- Streaming behavior contract (SSE/chunked expectations and completion semantics).
- Required metadata and correlation IDs.
- Failure semantics (what is returned/logged on capture-path faults).

### Acceptance Criteria
- Contract doc is committed and referenced by implementation issues.
- Provider/endpoint support matrix is explicit and testable.
- Streaming and failure semantics are unambiguous.

### Test Evidence
- Contract has a checklist that maps directly to tests in later issues.

---

## Issue GAP-PM-02: Build Listener Lifecycle Commands

**Type:** backend/cli  
**Priority:** P0  
**Depends on:** GAP-PM-01

### Objective
Implement robust listener lifecycle commands:
- `replaypack listen start`
- `replaypack listen stop`
- `replaypack listen status`
- `replaypack listen env`

### Scope
- PID/state management across macOS/Linux/Windows.
- Stale PID detection and recovery.
- Port allocation/conflict handling.
- Shell-friendly env output for routing app traffic.

### Acceptance Criteria
- Repeated start/stop cycles are stable with no orphaned listeners.
- Status reflects actual runtime state after normal exit and crash.
- `listen env` prints deterministic, copy/paste-safe env exports.

### Test Evidence
- Unit tests for PID/state transitions and stale PID cleanup.
- Integration test for start -> status -> stop -> status.

---

## Issue GAP-PM-03: Implement Provider HTTP Gateway

**Type:** backend/integration  
**Priority:** P0  
**Depends on:** GAP-PM-01, GAP-PM-02

### Objective
Create local listener gateway that accepts provider-compatible requests and returns provider-shaped responses.

### Scope
- Provider-compatible ingress for OpenAI/Anthropic/Gemini routes in scope.
- Upstream forwarding and response pass-through.
- Preserve provider response structure and status behavior.

### Acceptance Criteria
- Existing provider SDK/client calls can be routed through listener with minimal/no payload changes.
- Returned responses remain provider-shaped.
- Gateway handles non-2xx and timeout paths consistently with contract.

### Test Evidence
- E2E fixtures per provider proving request compatibility and response shape parity.

---

## Issue GAP-PM-04: Add Provider Adapters to ReplayKit Step Model

**Type:** backend/integration  
**Priority:** P0  
**Depends on:** GAP-PM-01, GAP-PM-03

### Objective
Normalize provider request/response traffic into ReplayKit run steps:
- `model.request`
- `model.response`

### Scope
- Adapter mapping for each provider.
- Correlation ID propagation.
- Preserve provider payloads unless normalization is strictly required.

### Acceptance Criteria
- Each provider flow emits canonical `model.request` and `model.response` steps.
- Provider-specific payload details needed for replay/debug are retained.
- Canonicalization is stable for deterministic replay.

### Test Evidence
- Adapter unit tests with representative provider payloads.
- Snapshot-style canonical output tests.

---

## Issue GAP-PM-05: Add Streaming Capture Support

**Type:** backend/streaming  
**Priority:** P0  
**Depends on:** GAP-PM-03, GAP-PM-04

### Objective
Capture streaming traffic (SSE/chunked) while also persisting a deterministic assembled final text/result.

### Scope
- Capture incremental chunks/events.
- Track stream boundaries and completion.
- Assemble and persist deterministic final output.

### Acceptance Criteria
- Stream events are captured in order with correlation IDs.
- Assembled final output is deterministic across repeated runs from same fixture.
- Stream interruptions/failures are represented clearly.

### Test Evidence
- Streaming E2E tests for at least one route per provider in scope.

---

## Issue GAP-PM-06: Persist Passive Artifacts Continuously (.rpk)

**Type:** backend/persistence  
**Priority:** P0  
**Depends on:** GAP-PM-04, GAP-PM-05

### Objective
Write `.rpk` artifacts continuously in passive mode with stable canonicalization/hashing.

### Scope
- Continuous write pipeline for passive capture.
- Correlation IDs, timestamps, and ordering guarantees.
- Stable canonicalization + hashing strategy.

### Acceptance Criteria
- Artifacts are incrementally persisted during long-running sessions.
- Hashes/canonical forms are stable for identical input traces.
- Artifacts are valid and replayable after abrupt listener termination.

### Test Evidence
- Persistence unit tests and abrupt-shutdown recovery test.

---

## Issue GAP-PM-07: Add Redaction and Secret Safety

**Type:** security  
**Priority:** P0  
**Depends on:** GAP-PM-04, GAP-PM-05, GAP-PM-06

### Objective
Redact auth headers, API keys, tokens, and common PII before writing any artifacts/logs.

### Scope
- Redaction on request path, response path, and logs.
- Header/body/query redaction policies.
- Token/PII detector coverage.

### Acceptance Criteria
- No raw secrets persisted in `.rpk` or logs.
- Redaction applies uniformly across providers and streaming/non-streaming flows.
- PII/token regression tests pass.

### Test Evidence
- Positive and negative leakage tests.
- Artifact scanning test that fails on known secret patterns.

---

## Issue GAP-PM-08: Add Failure Isolation Behavior

**Type:** reliability  
**Priority:** P0  
**Depends on:** GAP-PM-03, GAP-PM-04, GAP-PM-05, GAP-PM-06

### Objective
If capture path fails, protect app flow: return safe fallback responses and emit `error.event` steps without crashing user app flow.

### Scope
- Capture-path timeout/error handling.
- Best-effort mode defaults.
- `error.event` emission and observability hooks.

### Acceptance Criteria
- Listener/capture failures do not crash or block the routed app by default.
- Error steps are emitted with actionable diagnostics.
- Behavior aligns with contract failure semantics.

### Test Evidence
- Fault-injection tests for listener internal failures and upstream failures.

---

## Issue GAP-PM-09: Add Agent Passive Ingestion Endpoints (Codex, Claude Code)

**Type:** integration/agent  
**Priority:** P0  
**Depends on:** GAP-PM-01, GAP-PM-02, GAP-PM-04

### Objective
Add passive ingestion for coding-agent event streams and map them to ReplayKit run steps.

### Scope
- Endpoints/parsers for Codex event streams.
- Endpoints/parsers for Claude Code event streams.
- Canonical mapping and correlation with session/run metadata.

### Acceptance Criteria
- Both agent stream types ingest successfully in passive mode.
- Emitted run steps are consistent with provider-capture schema.
- Parse errors degrade gracefully and are observable.

### Test Evidence
- Fixture-based parser tests plus passive ingestion E2E.

---

## Issue GAP-PM-10: Preserve Replay Guarantees for Passive Artifacts

**Type:** replay/testing  
**Priority:** P0  
**Depends on:** GAP-PM-05, GAP-PM-06, GAP-PM-08, GAP-PM-09

### Objective
Ensure passive-captured artifacts replay offline deterministically in stub mode.

### Scope
- Replay parity checks (live capture vs offline replay).
- Canonical ordering/timestamp normalization assertions.
- Determinism and diff stability gates.

### Acceptance Criteria
- Repeated offline replays of the same artifact are byte-stable or canonically equivalent.
- Replay outputs match expected golden assertions in stub mode.

### Test Evidence
- Replay parity test suite with fixed fixtures and golden outputs.

---

## Issue GAP-PM-11: Add Full Test Coverage (Unit + E2E)

**Type:** qa/testing  
**Priority:** P0  
**Depends on:** GAP-PM-02, GAP-PM-03, GAP-PM-04, GAP-PM-05, GAP-PM-06, GAP-PM-07, GAP-PM-08, GAP-PM-09, GAP-PM-10

### Objective
Ship complete test coverage for passive mode.

### Required Test Flows
- Unit tests: adapters, redaction, listener state management.
- E2E flow: listener start -> app/provider call -> artifact capture -> offline replay -> assert.
- Streaming and non-streaming cases.

### Acceptance Criteria
- Coverage includes happy path and key failure paths.
- E2E tests prove full passive-mode operator flow.
- Test failures are actionable and localized.

---

## Issue GAP-PM-12: Wire CI Gates (Matrix + Regression)

**Type:** ci/devops  
**Priority:** P0  
**Depends on:** GAP-PM-11

### Objective
Add CI gates for passive mode reliability and regression prevention.

### Scope
- Matrix CI for ubuntu/macos/windows.
- Network-off replay tests.
- Listener cleanup/leak regression tests.

### Acceptance Criteria
- CI matrix runs passive-mode suites on all target OSes.
- Network-off replay determinism tests are mandatory gates.
- Cleanup/leak regressions are blocked before merge.

### Test Evidence
- CI workflow logs/artifacts proving matrix and gate execution.

---

## Issue GAP-PM-13: Document Operator Workflow

**Type:** docs/devx  
**Priority:** P1  
**Depends on:** GAP-PM-02, GAP-PM-03, GAP-PM-05, GAP-PM-08, GAP-PM-12

### Objective
Document how to run an app independently while routed through ReplayKit.

### Scope
- Setup and lifecycle commands.
- Env examples for provider routing.
- Streaming notes and limitations.
- Troubleshooting and recovery playbook.

### Acceptance Criteria
- A new operator can run passive mode end-to-end using docs only.
- Troubleshooting section covers common failures and verification steps.

---

## Issue GAP-PM-14: Define Release Criteria and Golden-Path Demo Artifact

**Type:** release/quality-gate  
**Priority:** P0  
**Depends on:** GAP-PM-07, GAP-PM-10, GAP-PM-12, GAP-PM-13

### Objective
Define and enforce release criteria for passive mode, including a golden-path demo artifact.

### Required Release Criteria
- Cross-platform CI green.
- No secret leakage in artifacts/logs.
- Deterministic replay parity achieved.
- Golden-path demo artifact committed/attached.

### Acceptance Criteria
- Release checklist is versioned in repo.
- Golden-path artifact can be replayed successfully in CI/stub mode.
- Sign-off criteria are explicit for future regressions.

---

## Suggested GitHub Issue Creation Order

1. GAP-PM-01  
2. GAP-PM-02  
3. GAP-PM-03  
4. GAP-PM-04  
5. GAP-PM-05  
6. GAP-PM-06  
7. GAP-PM-07  
8. GAP-PM-08  
9. GAP-PM-09  
10. GAP-PM-10  
11. GAP-PM-11  
12. GAP-PM-12  
13. GAP-PM-13  
14. GAP-PM-14

---

# Addendum: Codex Passive Capture Compatibility Gaps (2026-02-24)

## Observed Gap

When passive listener env routing is enabled (`OPENAI_BASE_URL=http://127.0.0.1:<port>`), `codex exec` sends requests to:

- `POST /responses`

Current listener behavior returns:

- `404 {"status":"error","message":"unsupported path"}`

Impact:

- Codex fails the run while routed through passive listener.
- Artifact remains empty (`steps=[]`) because no supported ingress route is hit.

---

## Issue GAP-CODEX-01: Add OpenAI Responses Endpoint Support in Passive Gateway

**Type:** backend/integration  
**Priority:** P0  
**Depends on:** GAP-PM-03

### Objective
Accept OpenAI Responses API paths in passive mode so Codex can route successfully.

### Scope
- Add ingress route detection for:
  - `POST /responses`
  - `POST /v1/responses`
- Preserve existing provider route behavior.
- Support deterministic synthetic response mode and optional upstream pass-through mode.

### Acceptance Criteria
- Routed Codex traffic no longer fails with `404 unsupported path`.
- Gateway returns valid OpenAI Responses-shaped payload for supported requests.
- Existing `/v1/chat/completions` behavior remains unchanged.

### Test Evidence
- Unit tests for route detection and provider selection.
- Integration tests for both `/responses` and `/v1/responses`.

---

## Issue GAP-CODEX-02: Normalize Responses API Payloads into ReplayKit Step Model

**Type:** backend/adapter  
**Priority:** P0  
**Depends on:** GAP-CODEX-01, GAP-PM-04

### Objective
Map OpenAI Responses request/response payloads into canonical ReplayKit steps.

### Scope
- Parse Responses-style request fields (`model`, `input`, optional `stream`, metadata).
- Normalize to deterministic:
  - `model.request`
  - `model.response`
- Preserve correlation metadata (`request_id`, `correlation_id`, provider/path/capture_mode).

### Acceptance Criteria
- `/responses` flows emit canonical model steps with deterministic ordering.
- Required metadata is present and stable across repeated identical requests.
- Artifacts are replayable and diffable with no schema regressions.

### Test Evidence
- Adapter tests with representative Responses payload fixtures.
- Canonical snapshot tests for normalized step output.

---

## Issue GAP-CODEX-03: Add Responses Streaming/Event Capture Semantics

**Type:** backend/streaming  
**Priority:** P1  
**Depends on:** GAP-CODEX-02, GAP-PM-05

### Objective
Capture Responses streaming/event output while preserving deterministic assembled output.

### Scope
- Handle `stream=true` request mode for `/responses`.
- Persist ordered stream events and deterministic assembled final text.
- Emit clear diagnostics for interrupted/malformed stream frames.

### Acceptance Criteria
- Stream capture records event_count, ordered events, completion state.
- Assembled text is deterministic for identical traces.
- Stream failures produce actionable diagnostics without breaking persistence.

### Test Evidence
- Streaming integration tests for `/responses`.
- Failure-path tests for malformed/interrupted stream payloads.

---

## Issue GAP-CODEX-04: Add Codex Passive E2E Regression Suite

**Type:** qa/e2e  
**Priority:** P0  
**Depends on:** GAP-CODEX-01, GAP-CODEX-02

### Objective
Prevent regressions where passive listener breaks Codex-compatible routing.

### Scope
- Listener lifecycle + routed `/responses` request + artifact assertion flow.
- Verify no `404 unsupported path` for supported Codex/OpenAI Responses routes.
- Keep tests network-independent by default.

### Acceptance Criteria
- End-to-end passive capture flow records non-empty steps for `/responses` fixture traffic.
- Replay + assert pass for captured artifact.
- Tests are deterministic and pass across CI OS matrix.

### Test Evidence
- New tests under passive listener E2E/CI suite.
- Included in `python3 -m pytest -q` default run.

---

## Issue GAP-CODEX-05: Update Docs for Codex Passive Routing and Known Limits

**Type:** docs/devx  
**Priority:** P1  
**Depends on:** GAP-CODEX-01, GAP-CODEX-04

### Objective
Document exact passive routing requirements for Codex and troubleshooting steps.

### Scope
- Update `README.md` and `docs/PASSIVE_LISTENER.md` with:
  - supported Codex/OpenAI routes (`/responses`, `/v1/responses`)
  - one-shell workflow example
  - expected artifact verification commands
  - troubleshooting for route mismatch

### Acceptance Criteria
- Operator docs let a new user run passive Codex capture without wrapper mode.
- Troubleshooting section includes concrete error and fix for `unsupported path`.

### Test Evidence
- Doc command snippets are validated in CI smoke checks or scripted manual test notes.

---

## Suggested GitHub Issue Creation Order (Codex Addendum)

1. GAP-CODEX-01  
2. GAP-CODEX-02  
3. GAP-CODEX-04  
4. GAP-CODEX-03  
5. GAP-CODEX-05  

---

# Addendum: True Transparent Background Mode (No Routing Env Changes, macOS MVP First)

## Objective

Enable ReplayKit to capture LLM/coding-agent traffic without wrapping the target process and without requiring users to export routing env vars (for example `OPENAI_BASE_URL`).

## MVP Scope (macOS First)

- User starts ReplayKit transparent listener once.
- User runs tools normally (`codex`, apps, scripts) in any shell.
- ReplayKit captures supported provider traffic in background.
- User stops listener and gets replayable `.rpk` artifact.

## Non-Negotiable Invariants

- No secrets persisted in artifacts/logs.
- Replay remains deterministic and offline-compatible.
- Stop/rollback fully restores system networking state.
- Failure in capture path must not leave machine networking in broken state.

---

## Issue GAP-TM-01: macOS Transparent Mode Contract + CLI Scaffolding

**Type:** backend/cli  
**Priority:** P0  
**Depends on:** none

### Objective
Define and implement initial transparent mode surface for macOS MVP:
- `replaypack listen transparent start`
- `replaypack listen transparent stop`
- `replaypack listen transparent status`
- `replaypack listen transparent doctor`

### Scope
- Add transparent-mode state file schema (session, mode, rollback handles placeholder).
- Add CLI command group and JSON/non-JSON outputs with deterministic fields.
- Implement `doctor` checks for macOS prerequisites (platform, required binaries, privilege expectations) without mutating system state.
- Keep existing passive `listen` behavior unchanged.

### Acceptance Criteria
- Transparent subcommands exist and return stable machine-readable payloads.
- `doctor` reports actionable readiness checks on macOS.
- `start/stop/status` persist/read transparent state cleanly.
- Full test suite remains green.

### Test Evidence
- New CLI tests for transparent lifecycle + doctor.
- `python3 -m pytest -q`.

---

## Issue GAP-TM-02: macOS Network Intercept Controller (Safe Apply/Revert)

**Type:** backend/os-integration  
**Priority:** P0  
**Depends on:** GAP-TM-01

### Objective
Implement macOS-only network interception controller with explicit rollback.

### Scope
- Apply interception rules for transparent mode start.
- Persist rollback plan and execute on stop/crash recovery.
- Add stale-session recovery path that reverts orphaned rules.

### Acceptance Criteria
- Start applies rules once; repeated start is idempotent.
- Stop always attempts rollback and reports result.
- Crash/stale recovery removes orphaned rules.

### Test Evidence
- Unit tests for controller state transitions and rollback journaling.
- Safe mocked command-runner tests (no real system mutation in CI).

---

## Issue GAP-TM-03: Transparent Gateway Compatibility for OpenAI/Codex Core Paths

**Type:** backend/integration  
**Priority:** P0  
**Depends on:** GAP-TM-01, GAP-TM-02

### Objective
Make transparent gateway satisfy Codex/OpenAI baseline control-plane/data-plane requests.

### Scope
- Ensure support for required paths used during Codex startup/execution:
  - `/models` (where required by client behavior)
  - `/responses`
  - `/v1/responses`
- Preserve provider-shaped status codes and response contracts.
- Emit canonical `model.request`/`model.response` steps with path metadata.

### Acceptance Criteria
- `codex exec` through transparent mode no longer fails on unsupported core paths.
- Captured artifacts contain non-empty model steps for live fixture traffic.
- Existing passive-mode compatibility is preserved.

### Test Evidence
- Listener gateway integration tests for `/models` and responses routes.
- Regression test proving no `unsupported path` for supported paths.

---

## Issue GAP-TM-04: Transparent Streaming Semantics + Deterministic Assembly

**Type:** backend/streaming  
**Priority:** P1  
**Depends on:** GAP-TM-03

### Objective
Capture streaming response events in transparent mode while persisting deterministic assembled output.

### Scope
- Ordered event capture with correlation IDs.
- Completion/error semantics and diagnostics.
- Deterministic assembled text persistence.

### Acceptance Criteria
- Stream events recorded in order with completion state.
- Assembled output stable for repeated fixture input.
- Failure diagnostics emitted without artifact corruption.

### Test Evidence
- Streaming integration tests + failure-path tests.

---

## Issue GAP-TM-05: Security Hardening for Transparent Mode

**Type:** security  
**Priority:** P0  
**Depends on:** GAP-TM-03, GAP-TM-04

### Objective
Guarantee transparent mode does not persist secrets/tokens/PII.

### Scope
- Redaction for headers/body/query/log diagnostics in transparent paths.
- Explicit denylist coverage for auth artifacts.
- Artifact scan checks for known secret patterns.

### Acceptance Criteria
- No raw secrets found in transparent artifacts/logs.
- Redaction behavior consistent with passive mode policies.
- Security regression suite passes.

### Test Evidence
- Leakage regression tests + artifact scanner tests.

---

## Issue GAP-TM-06: macOS Transparent E2E + Replay Parity Gates

**Type:** qa/e2e  
**Priority:** P0  
**Depends on:** GAP-TM-03, GAP-TM-04, GAP-TM-05

### Objective
Prove full macOS transparent flow: start -> run target normally -> stop -> replay/assert.

### Scope
- Deterministic fixture-driven E2E (CI-safe with mocks where needed).
- Optional manual smoke path for real `codex exec`.
- Replay parity and first-divergence validation.

### Acceptance Criteria
- End-to-end transparent capture produces valid non-empty `.rpk`.
- Replay+assert pass offline with fixed seed/clock.
- Determinism/parity checks are stable.

### Test Evidence
- New e2e tests + documented manual smoke command sequence.

---

## Issue GAP-TM-07: Docs + Operator Runbook for Transparent Mode

**Type:** docs/devx  
**Priority:** P1  
**Depends on:** GAP-TM-01, GAP-TM-06

### Objective
Document transparent-mode operation and recovery.

### Scope
- README + `docs/PASSIVE_LISTENER.md` updates with transparent commands.
- macOS limitations, permissions, rollback guidance.
- Troubleshooting for startup failures and cleanup verification.

### Acceptance Criteria
- New operator can execute macOS transparent flow from docs only.
- Recovery instructions cover partial-failure and stale-state scenarios.

### Test Evidence
- Doc snippets are command-validated in smoke script/manual checklist.

---

## Suggested GitHub Issue Creation Order (Transparent Addendum)

1. GAP-TM-01  
2. GAP-TM-02  
3. GAP-TM-03  
4. GAP-TM-04  
5. GAP-TM-05  
6. GAP-TM-06  
7. GAP-TM-07  

---

# Addendum: Production Readiness Gaps from Codex Passive Demo Artifact (2026-02-26)

## Evidence Summary

Artifact reviewed: `runs/manual/codex-passive-demo.rpk`

Observed:
- Exactly 2 steps: `model.request`, `model.response`.
- No `tool.request`/`tool.response` steps.
- `response_source` is synthetic.
- Captured payload contains large instruction/context body.
- Authorization is redacted, but broader body/query/log redaction guarantees still need explicit coverage.

## Objective

Promote passive listener behavior from demo-safe synthetic capture to production-safe, real-traffic capture with deterministic replay guarantees and security controls.

---

## Issue GAP-PR-01: Set Production Capture Policy (Live Pass-Through Default)

**Type:** backend/policy  
**Priority:** P0  
**Depends on:** GAP-PM-01, GAP-PM-03

### Objective
Define and enforce a production policy where live pass-through is the default capture mode, and synthetic mode is explicit opt-in.

### Scope
- Add explicit listener mode policy flags (`live`, `synthetic`).
- Default to live pass-through in production mode.
- Add hard warnings in CLI/UI/JSON when synthetic mode is active.

### Acceptance Criteria
- Production listener start defaults to live pass-through.
- Synthetic mode requires explicit opt-in.
- Artifact metadata always records mode and policy source.

### Test Evidence
- CLI policy tests for default mode and explicit synthetic opt-in.
- Integration tests asserting metadata mode fields.

---

## Issue GAP-PR-02: Add Synthetic-Mode Guardrails and Fail-Closed Options

**Type:** backend/reliability  
**Priority:** P0  
**Depends on:** GAP-PR-01

### Objective
Prevent accidental use of synthetic responses in production runs.

### Scope
- Add `--fail-on-synthetic`/config equivalent for strict environments.
- Emit `error.event` when strict mode blocks synthetic fallback.
- Add machine-readable status fields in listener outputs.

### Acceptance Criteria
- Strict mode blocks synthetic fallback and exits non-zero.
- Non-strict mode still records explicit synthetic marker.
- Operator can detect synthetic usage from JSON output alone.

### Test Evidence
- Listener strict/non-strict fallback tests.
- Regression tests verifying exit codes and `error.event` behavior.

---

## Issue GAP-PR-03: Capture Codex Tool/Action Semantics as `tool.*` Steps

**Type:** backend/adapter  
**Priority:** P0  
**Depends on:** GAP-CODEX-02

### Objective
Convert provider/agent payload structures that represent tool usage into canonical `tool.request` and `tool.response` steps.

### Scope
- Parse response payload tool-call/tool-result structures.
- Map to deterministic ReplayKit tool steps with correlation IDs.
- Keep `model.*` steps for full request/response trace.

### Acceptance Criteria
- Tool-bearing fixtures emit both `model.*` and `tool.*` steps.
- Step ordering is deterministic and replay-stable.
- UI diff shows tool steps for Codex-compatible traffic.

### Test Evidence
- Adapter fixture tests for tool-call and tool-output mapping.
- End-to-end passive capture test verifying non-empty tool steps.

---

## Issue GAP-PR-04: Enforce Capture Payload Minimization and Allowlist Controls

**Type:** security/privacy  
**Priority:** P1  
**Depends on:** GAP-PR-01

### Objective
Reduce captured request surface to debugging-essential fields by default, with explicit allowlist expansion controls.

### Scope
- Define per-provider default capture allowlist.
- Truncate/drop non-essential high-volume fields.
- Add config for opt-in full body capture with warning banner.

### Acceptance Criteria
- Default artifacts exclude non-essential large instruction blobs.
- Required replay/debug fields remain present.
- Full body capture requires explicit opt-in.

### Test Evidence
- Snapshot tests for minimized payload shape.
- Replay parity tests proving minimized artifacts still replay.

---

## Issue GAP-PR-05: Harden Redaction Across Headers, Body, Query, and Logs

**Type:** security  
**Priority:** P0  
**Depends on:** GAP-PM-07, GAP-PR-04

### Objective
Guarantee no secrets/tokens/PII leak into artifacts and listener logs.

### Scope
- Deep redaction for nested request/response fields.
- Query parameter scrubbing.
- Structured log redaction aligned with artifact redaction policies.

### Acceptance Criteria
- No raw secret patterns in artifacts or logs.
- Redaction behavior is consistent across streaming and non-streaming flows.
- CI fails on known secret leakage patterns.

### Test Evidence
- Positive/negative redaction tests.
- Artifact/log scanner test suite in default CI run.

---

## Issue GAP-PR-06: Improve Streaming Fidelity and Completion Semantics

**Type:** backend/streaming  
**Priority:** P0  
**Depends on:** GAP-CODEX-03

### Objective
Capture provider-accurate streaming semantics while preserving deterministic assembled output.

### Scope
- Preserve provider event types and ordering.
- Persist stream completion/error states with diagnostics.
- Validate deterministic assembly from streamed deltas.

### Acceptance Criteria
- Stream metadata distinguishes clean completion vs interrupted streams.
- Assembled output is deterministic from identical traces.
- Provider-specific event fidelity is retained for debugging.

### Test Evidence
- Streaming integration tests with clean and interrupted flows.
- Canonicalization tests for deterministic assembled text.

---

## Issue GAP-PR-07: Strengthen Upstream Failure Isolation and Recovery

**Type:** reliability  
**Priority:** P0  
**Depends on:** GAP-PM-08, GAP-PR-01

### Objective
Ensure listener errors do not silently degrade production behavior and provide explicit operator controls.

### Scope
- Policy-driven retry/backoff and timeout controls.
- Explicit fallback policies (`live_only`, `best_effort`, `synthetic_allowed`).
- Actionable diagnostics for upstream failures.

### Acceptance Criteria
- Listener behavior is policy-consistent under upstream faults.
- `error.event` includes actionable diagnostics and policy outcome.
- No hidden fallback to synthetic in strict production mode.

### Test Evidence
- Fault-injection tests for timeout, 5xx, malformed payload, and disconnects.
- Policy matrix tests for fallback behavior.

---

## Issue GAP-PR-08: Expand Provider/Codex Route Compatibility Coverage

**Type:** backend/integration  
**Priority:** P0  
**Depends on:** GAP-CODEX-01, GAP-TM-03

### Objective
Guarantee compatibility for all core routes used during real Codex/OpenAI startup and execution.

### Scope
- Validate supported path/method matrix:
  - `/models`
  - `/responses`
  - `/v1/responses`
  - other currently implemented OpenAI-compatible paths in contract
- Add explicit unsupported-route diagnostics.

### Acceptance Criteria
- Supported routes no longer return unexpected `404 unsupported path`.
- Unsupported routes return contract-defined errors with remediation hint.
- Route compatibility matrix is documented and tested.

### Test Evidence
- Route matrix integration tests.
- Regression tests for previously failing Codex paths.

---

## Issue GAP-PR-09: Add Replay Parity Gates for Live-Capture Artifacts

**Type:** qa/replay  
**Priority:** P0  
**Depends on:** GAP-PR-03, GAP-PR-06, GAP-PR-07

### Objective
Prevent production regressions by gating on replay determinism and first-divergence stability for live-capture flows.

### Scope
- Add golden live-capture fixtures (sanitized) for passive mode.
- Enforce replay parity checks in CI.
- Validate first-divergence output stability.

### Acceptance Criteria
- Repeated stub replays from same artifact are canonically stable.
- First-divergence output remains deterministic for fixed fixtures.
- CI blocks merges on parity regressions.

### Test Evidence
- Replay parity test suite with fixture hashes.
- CI job artifacts demonstrating deterministic outputs.

---

## Issue GAP-PR-10: Add Operational Controls (Health, Rotation, Retention)

**Type:** ops/devx  
**Priority:** P1  
**Depends on:** GAP-PM-02, GAP-PR-09

### Objective
Ship operator-grade controls for long-running passive capture sessions.

### Scope
- Listener health endpoints/status metrics.
- Artifact rotation strategy (size/time-based).
- Retention/cleanup commands and policies.

### Acceptance Criteria
- Operators can run passive listener long-term without manual cleanup.
- Health/status outputs expose capture errors and degraded state clearly.
- Rotation/retention policies prevent unbounded artifact growth.

### Test Evidence
- Lifecycle tests for rotation and retention.
- Status/metrics tests for healthy/degraded states.

---

## Suggested GitHub Issue Creation Order (Production Readiness Addendum)

1. GAP-PR-01  
2. GAP-PR-02  
3. GAP-PR-03  
4. GAP-PR-04  
5. GAP-PR-05  
6. GAP-PR-06  
7. GAP-PR-07  
8. GAP-PR-08  
9. GAP-PR-09  
10. GAP-PR-10  
