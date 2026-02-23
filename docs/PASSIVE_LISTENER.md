# Passive Listener Mode

ReplayKit passive mode runs as a local listener/interceptor so target apps and coding agents can run independently while ReplayKit captures canonical debugging artifacts.

## What It Captures

- Provider gateway traffic to listener paths:
  - OpenAI-compatible: `/v1/chat/completions`
  - Anthropic-compatible: `/v1/messages`
  - Gemini-compatible: `/v1beta/models/<model>:generateContent`
- Agent event streams:
  - Codex: `/agent/codex/events`
  - Claude Code: `/agent/claude-code/events`

Captured artifacts include canonical `model.request`, `model.response`, `tool.request`, `tool.response`, and `error.event` steps.

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

## Health and Failure Isolation

`listen status --json` includes `health.metrics`:

- `capture_errors`
- `dropped_events`
- `degraded_responses`

Best-effort behavior is enabled by default:

- If capture internals fail, listener returns degraded fallback provider responses and records diagnostics as `error.event`.
- Malformed agent frames are dropped with diagnostics and metrics increments.

## Security

Listener persistence enforces redaction before artifact writes:

- Sensitive headers are masked (`authorization`, token/key/secret-like names).
- Sensitive payload fields (tokens, API keys, passwords, cookies) are masked.
- Secret-like patterns in string values are redacted.

Caveats:

- Redaction is policy-driven and heuristic for unknown/custom formats.
- Validate redaction coverage for proprietary payload schemas before sharing artifacts.

## Troubleshooting

- `listener start failed: requested port is unavailable`:
  - Pick a different port or use `--port 0`.
- `listen env failed: listener is not running`:
  - Start listener first, then re-run `listen env`.
- Repeated `dropped_events` in health metrics:
  - Verify agent payload is JSON object/list with expected `type` fields.
- `capture_errors` increasing:
  - Inspect `error.event` steps in artifact and check CI/uploaded logs under `runs/passive`.
