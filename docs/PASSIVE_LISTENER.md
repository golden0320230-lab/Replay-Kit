# Passive Listener Mode

ReplayKit passive mode runs as a local listener/interceptor so target apps and coding agents can run independently while ReplayKit captures canonical debugging artifacts.

Passive contract details (provider matrix, streaming semantics, failure semantics):
`docs/PASSIVE_LISTENER_ARCHITECTURE.md`

## What It Captures

- Provider gateway traffic to listener paths:
  - OpenAI-compatible: `/v1/chat/completions`
  - OpenAI Responses-compatible: `/responses`, `/v1/responses`
  - Anthropic-compatible: `/v1/messages`
  - Gemini-compatible: `/v1beta/models/<model>:generateContent`
- Agent event streams:
  - Codex: `/agent/codex/events`
  - Claude Code: `/agent/claude-code/events`
  - Payload formats: JSON object, JSON array, or newline-delimited JSON (JSONL)

Captured artifacts include canonical `model.request`, `model.response`, `tool.request`, `tool.response`, and `error.event` steps.

Provider adapter normalization guarantees:

- Every provider request/response pair is emitted as `model.request` then `model.response`.
- Provider payload details are retained with deterministic key ordering for stable replay/diff output.
- `correlation_id` and `request_id` metadata are propagated on both request and response steps.

## Commands

Start listener daemon:

```bash
replaykit listen start --json
```

Stop listener daemon:

```bash
replaykit listen stop --json
```

Inspect listener status and health metrics:

```bash
replaykit listen status --json
```

Print shell exports for routing app traffic to listener:

```bash
replaykit listen env --shell bash
replaykit listen env --shell powershell
replaykit listen env --json
```

Lifecycle behavior:

- `listen start` auto-cleans stale state files when the recorded PID is no longer running.
- `listen status` reports `running=false` and `stale_cleanup=true` after stale-state recovery.
- `listen stop` is idempotent and safe to call repeatedly.
- `listen env` output is deterministic and copy/paste-safe for both bash and PowerShell.

## Transparent Mode (macOS MVP)

Transparent mode adds macOS interception lifecycle control with rollback safety:

```bash
replaykit listen transparent doctor --state-file runs/transparent/state.json --json
replaykit listen transparent start --state-file runs/transparent/state.json --json
replaykit listen transparent status --state-file runs/transparent/state.json --json
replaykit listen transparent stop --state-file runs/transparent/state.json --json
```

Operational model:

- Transparent and passive modes use different state files; keep them separate.
- Transparent mode controls OS interception state; passive `listen start|stop` controls artifact capture daemon.
- `REPLAYKIT_TRANSPARENT_EXECUTE` is disabled by default for safe dry-run behavior.
- To execute OS mutation steps, set `REPLAYKIT_TRANSPARENT_EXECUTE=1` and run with required privileges (commonly root on macOS).

macOS MVP runbook (command-validated):

```bash
mkdir -p runs/transparent runs/passive
replaykit listen transparent doctor --state-file runs/transparent/state.json --json
replaykit listen transparent start --state-file runs/transparent/state.json --json
replaykit listen start --state-file runs/passive/state.json --out runs/passive/transparent-capture.rpk --json
eval "$(replaykit listen env --state-file runs/passive/state.json --shell bash)"
codex exec --json "say hello from transparent runbook"
replaykit listen stop --state-file runs/passive/state.json --json
replaykit listen transparent stop --state-file runs/transparent/state.json --json
replaykit listen transparent status --state-file runs/transparent/state.json --json
replaykit assert runs/passive/transparent-capture.rpk --candidate runs/passive/transparent-capture.rpk --json
```

Current transparent limitations:

- macOS-only support.
- Default mode is rollback-safe scaffolding (`REPLAYKIT_TRANSPARENT_EXECUTE` off).
- Full no-env background routing is not complete; use `listen env` or explicit base URL overrides for deterministic capture today.

## Typical Workflow

1. Start listener:

```bash
replaykit listen start --state-file runs/passive/state.json --out runs/passive/capture.rpk --json
```

2. Emit routing exports:

```bash
replaykit listen env --state-file runs/passive/state.json --shell bash
```

3. Run your app/agent normally (outside ReplayKit wrappers), sending provider/agent traffic to listener URLs.

4. Stop listener:

```bash
replaykit listen stop --state-file runs/passive/state.json --json
```

5. Assert and replay:

```bash
replaykit assert runs/passive/capture.rpk --candidate runs/passive/capture.rpk --json
replaykit replay runs/passive/capture.rpk --out runs/passive/replay.rpk --seed 19 --fixed-clock 2026-02-23T00:00:00Z
```

## One-Shell Codex Workflow

Use a single shell so `listen env` exports are active for `codex exec`:

```bash
mkdir -p runs/passive
replaykit listen start --state-file runs/passive/state.json --out runs/passive/codex-passive.rpk --json
eval "$(replaykit listen env --state-file runs/passive/state.json --shell bash)"
codex exec --json "say hello"
replaykit listen stop --state-file runs/passive/state.json --json
replaykit assert runs/passive/codex-passive.rpk --candidate runs/passive/codex-passive.rpk --json
```

Expected artifact characteristics:

- At least one `model.request` and `model.response` pair for `/responses` or `/v1/responses`.
- `step.metadata.provider == "openai"` on Responses-captured steps.

## Optional Upstream Pass-Through

By default, listener gateway returns deterministic provider-shaped synthetic responses. For live provider pass-through, set upstream base URLs before `listen start`:

```bash
export REPLAYKIT_OPENAI_UPSTREAM_URL="https://api.openai.com"
export REPLAYKIT_ANTHROPIC_UPSTREAM_URL="https://api.anthropic.com"
export REPLAYKIT_GEMINI_UPSTREAM_URL="https://generativelanguage.googleapis.com"
export REPLAYKIT_LISTENER_UPSTREAM_TIMEOUT_SECONDS="5"
```

Behavior:

- Successful upstream calls pass through status code and JSON body unchanged.
- Upstream non-2xx responses are passed through with provider response shape preserved.
- Upstream timeout/transport errors return `502` with `listener_gateway_error` payload and are captured in artifact steps.

## Operator Checklist

Use this checklist when running passive mode manually:

1. Start listener with explicit state and output paths.
2. Run `listen status --json` and confirm:
   - `running: true`
   - `health.status: "ok"`
3. Print exports with `listen env` and route your app/agent to listener URLs.
4. Execute at least one provider call and one agent event sequence.
5. Stop listener and verify artifact exists:
   - `runs/passive/capture.rpk`
6. Run deterministic validation:
   - `replaykit replay runs/passive/capture.rpk --out runs/passive/replay.rpk --seed 19 --fixed-clock 2026-02-23T00:00:00Z`
   - `replaykit assert runs/passive/replay.rpk --candidate runs/passive/replay.rpk --json`

If any checklist item fails, use the recovery playbook below before re-running.

## Streaming Notes and Limits

- Provider requests with `stream: true` are captured as normal passive gateway traffic.
- Passive listener preserves request order and correlation metadata, then records deterministic `model.*` steps for replay/diff.
- Streaming capture is best-effort: if malformed frames are encountered, they are dropped and reflected in `dropped_events`.
- Replay remains stub/offline for captured artifacts; passive mode is for debugging determinism and divergence, not live stream rehydration.

## Health and Failure Isolation

`listen status --json` includes `health.metrics`:

- `capture_errors`
- `dropped_events`
- `degraded_responses`

Best-effort behavior is enabled by default:

- If capture internals fail, listener returns degraded fallback provider responses and records diagnostics as `error.event`.
- Malformed agent frames are dropped with diagnostics (`parse_error` in response + `error.event`) and metrics increments.
- Passive `.rpk` writes are atomic, so abrupt listener termination keeps the last committed artifact valid.

## Security

Listener persistence enforces redaction before artifact writes:

- Sensitive headers are masked (`authorization`, token/key/secret-like names).
- Sensitive payload fields (tokens, API keys, passwords, cookies) are masked.
- Sensitive query parameters are masked before request step persistence.
- Secret-like patterns in string values are redacted.

Caveats:

- Redaction is policy-driven and heuristic for unknown/custom formats.
- Validate redaction coverage for proprietary payload schemas before sharing artifacts.

## Streaming Capture Semantics

For provider requests with `stream=true`, passive listener artifacts store:

- `output.stream.enabled`: stream mode requested.
- `output.stream.events`: ordered incremental `delta_text` events with 1-based indexes.
- `output.stream.event_count`: number of captured incremental events.
- `output.stream.completed`: true on successful stream completion, false when the stream fails/interrupted.

`output.assembled_text` remains the deterministic concatenation of ordered stream deltas.

## Troubleshooting

- `listener start failed: requested port is unavailable`:
  - Pick a different port or use `--port 0`.
- `listen env failed: listener is not running`:
  - Start listener first, then re-run `listen env`.
- Repeated `dropped_events` in health metrics:
  - Verify agent payload is JSON object/list/JSONL with expected `type` fields.
- `capture_errors` increasing:
  - Inspect `error.event` steps in artifact and check CI/uploaded logs under `runs/passive`.
- `listen transparent start failed: required intercept operation failed`:
  - Run `replaykit listen transparent doctor --state-file runs/transparent/state.json --json` and resolve failed checks.
  - If applying real intercept rules, retry with privilege escalation and `REPLAYKIT_TRANSPARENT_EXECUTE=1`.
- `listen transparent ... state file belongs to passive listener mode`:
  - Use separate state paths, for example:
    - transparent: `runs/transparent/state.json`
    - passive: `runs/passive/state.json`
- `listen transparent stop failed: rollback operation failed`:
  - Re-run stop with the same `REPLAYKIT_TRANSPARENT_EXECUTE` value used at start.
  - Verify status and stale cleanup:
    - `replaykit listen transparent status --state-file runs/transparent/state.json --json`
- `codex exec` shows `unsupported path ... /responses`:
  - Ensure your ReplayKit build includes OpenAI Responses routes (`/responses`, `/v1/responses`).
  - Re-run `listen env` in the same shell where `codex exec` runs.
  - Verify the listener by probing one route directly:
    - `curl -sS "$OPENAI_BASE_URL/responses" -H "content-type: application/json" -d '{"model":"gpt-5.3-codex","input":"ping"}'`

## Recovery Playbook

When passive mode enters a bad state, run this sequence:

1. Hard stop listener session:

```bash
replaykit listen stop --state-file runs/passive/state.json --json
```

2. Verify listener is fully down:

```bash
replaykit listen status --state-file runs/passive/state.json --json
```

3. Start a fresh session with a new output artifact path:

```bash
replaykit listen start --state-file runs/passive/state.json --out runs/passive/recover-capture.rpk --json
```

4. Re-run minimal probe traffic (one provider request, one agent event payload), then stop.

5. Validate resulting artifact before continuing:

```bash
replaykit assert runs/passive/recover-capture.rpk --candidate runs/passive/recover-capture.rpk --json
```
