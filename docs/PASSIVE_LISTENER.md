# Passive Listener Mode

ReplayKit passive mode runs as a local listener/interceptor so target apps and coding agents can run independently while ReplayKit captures canonical debugging artifacts.

Passive contract details (provider matrix, streaming semantics, failure semantics):
`docs/PASSIVE_LISTENER_ARCHITECTURE.md`

## What It Captures

- Provider gateway traffic to listener paths:
  - OpenAI-compatible: `/v1/chat/completions`
  - Anthropic-compatible: `/v1/messages`
  - Gemini-compatible: `/v1beta/models/<model>:generateContent`
- Agent event streams:
  - Codex: `/agent/codex/events`
  - Claude Code: `/agent/claude-code/events`

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

## Health and Failure Isolation

`listen status --json` includes `health.metrics`:

- `capture_errors`
- `dropped_events`
- `degraded_responses`

Best-effort behavior is enabled by default:

- If capture internals fail, listener returns degraded fallback provider responses and records diagnostics as `error.event`.
- Malformed agent frames are dropped with diagnostics and metrics increments.
- Passive `.rpk` writes are atomic, so abrupt listener termination keeps the last committed artifact valid.

## Security

Listener persistence enforces redaction before artifact writes:

- Sensitive headers are masked (`authorization`, token/key/secret-like names).
- Sensitive payload fields (tokens, API keys, passwords, cookies) are masked.
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
  - Verify agent payload is JSON object/list with expected `type` fields.
- `capture_errors` increasing:
  - Inspect `error.event` steps in artifact and check CI/uploaded logs under `runs/passive`.
