# ReplayKit Local UI (M7)

## Scope

M7 delivers a local-first Git-diff style UI for artifact inspection.

## Command

```bash
replaykit ui
```

Useful options:

```bash
replaykit ui --host 127.0.0.1 --port 4310
replaykit ui --left examples/runs/m2_capture_boundaries.rpk --right examples/runs/m4_diverged_from_m2.rpk
replaykit ui --browser
replaykit ui --check
```

## Features

- Runs locally with no external network dependency
- Discovers artifacts from `runs/` and `examples/runs/`
- Loads structured diff via local API
- Left panel: step statuses and selection
- Center panel: side-by-side change payloads
- Right panel: metadata context for selected step
- Jump-to-first-divergence action
- Explicit empty/failure states for missing files and bad requests

## API Endpoints (local)

- `GET /api/files` -> discovered artifact paths
- `GET /api/diff?left=...&right=...` -> structured diff payload

## Accessibility Baseline

- Heading structure includes top-level `<h1>` and panel headings
- Form controls use explicit `<label for=...>` associations
- Status line is announced via `aria-live="polite"`
- Step items are keyboard-selectable (`Enter`/`Space`)
