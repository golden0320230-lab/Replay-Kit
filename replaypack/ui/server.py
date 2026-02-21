"""Local-first UI server for artifact diff inspection."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Iterator
from urllib.parse import parse_qs, quote, unquote, urlparse

from replaypack.artifact import ArtifactError, read_artifact
from replaypack.diff import diff_runs

_SUPPORTED_SUFFIXES = {".rpk", ".bundle"}


@dataclass(slots=True)
class UIServerConfig:
    host: str = "127.0.0.1"
    port: int = 4310
    base_dir: Path = Path.cwd()


def build_ui_url(
    host: str,
    port: int,
    *,
    left: str | None = None,
    right: str | None = None,
) -> str:
    query_parts: list[str] = []
    if left:
        query_parts.append(f"left={quote(left)}")
    if right:
        query_parts.append(f"right={quote(right)}")
    query = "&".join(query_parts)
    suffix = f"/?{query}" if query else "/"
    return f"http://{host}:{port}{suffix}"


def list_local_artifacts(base_dir: Path) -> list[str]:
    """Discover artifacts in known local directories."""
    candidates: list[Path] = []
    for relative_dir in ("runs", "examples/runs"):
        directory = (base_dir / relative_dir).resolve()
        if not directory.exists() or not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.is_file() and child.suffix in _SUPPORTED_SUFFIXES:
                candidates.append(child)

    unique = sorted(set(candidates))
    output: list[str] = []
    for item in unique:
        try:
            output.append(str(item.relative_to(base_dir)))
        except ValueError:
            output.append(str(item))
    return output


def create_ui_server(config: UIServerConfig) -> ThreadingHTTPServer:
    base_dir = config.base_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            route = parsed.path
            query = parse_qs(parsed.query)

            if route == "/":
                self._write_html(_render_index_html())
                return

            if route == "/api/files":
                files = list_local_artifacts(base_dir)
                self._write_json(200, {"files": files})
                return

            if route == "/api/diff":
                self._handle_diff(query)
                return

            self._write_json(404, {"error": "Not found"})

        def _handle_diff(self, query: dict[str, list[str]]) -> None:
            left_raw = _first(query.get("left"))
            right_raw = _first(query.get("right"))

            if not left_raw or not right_raw:
                self._write_json(
                    400,
                    {
                        "error": (
                            "Missing required query params: left and right"
                        )
                    },
                )
                return

            try:
                left_path = _resolve_artifact_path(base_dir, left_raw)
                right_path = _resolve_artifact_path(base_dir, right_raw)
                left_run = read_artifact(left_path)
                right_run = read_artifact(right_path)
                diff = diff_runs(left_run, right_run)
            except (FileNotFoundError, ArtifactError, ValueError) as error:
                self._write_json(400, {"error": str(error)})
                return

            payload = diff.to_dict()
            payload["left_path"] = _display_path(base_dir, left_path)
            payload["right_path"] = _display_path(base_dir, right_path)
            self._write_json(200, payload)

        def _write_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_json(self, status_code: int, payload: dict) -> None:
            body = (
                json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            )
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer((config.host, config.port), Handler)


@contextmanager
def start_ui_server(config: UIServerConfig) -> Iterator[tuple[ThreadingHTTPServer, threading.Thread]]:
    server = create_ui_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, thread
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _resolve_artifact_path(base_dir: Path, raw_path: str) -> Path:
    candidate = Path(unquote(raw_path))
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if candidate.suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError("Only .rpk and .bundle files are supported")

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Artifact not found: {candidate}")

    return candidate


def _display_path(base_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _render_index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ReplayKit Local UI</title>
  <style>
    :root {
      --bg: #f7f4ed;
      --panel: #fffdfa;
      --ink: #1f2933;
      --accent: #0f766e;
      --changed: #b45309;
      --identical: #047857;
      --missing: #7c2d12;
      --muted: #6b7280;
      --border: #d6d3d1;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Trebuchet MS", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 20% 10%, #efe8d8 0%, transparent 40%),
        radial-gradient(circle at 90% 0%, #d7eee7 0%, transparent 35%),
        var(--bg);
      min-height: 100vh;
    }

    header {
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 253, 250, 0.9);
      backdrop-filter: blur(2px);
    }

    h1 {
      margin: 0;
      font-size: 1.5rem;
      letter-spacing: 0.02em;
    }

    .sub {
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.95rem;
    }

    .controls {
      display: grid;
      grid-template-columns: repeat(2, minmax(260px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }

    label {
      display: block;
      font-size: 0.85rem;
      margin-bottom: 6px;
      font-weight: 600;
    }

    input {
      width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      font-size: 0.92rem;
    }

    .actions {
      margin-top: 12px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    button {
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--ink);
      padding: 8px 12px;
      border-radius: 999px;
      cursor: pointer;
      font-weight: 600;
    }

    button.primary {
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }

    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .status {
      margin-top: 10px;
      min-height: 1.2em;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .layout {
      display: grid;
      grid-template-columns: 290px 1fr 340px;
      gap: 14px;
      padding: 16px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      min-height: 56vh;
      overflow: hidden;
    }

    .panel h2 {
      margin: 0;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      font-size: 0.98rem;
      background: #f5f3ee;
    }

    .panel-body {
      padding: 10px;
      height: calc(56vh - 44px);
      overflow: auto;
    }

    .steps {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .step-item {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      padding: 8px;
      cursor: pointer;
    }

    .step-item.active {
      outline: 2px solid var(--accent);
    }

    .step-status {
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .status-identical { color: var(--identical); }
    .status-changed { color: var(--changed); }
    .status-missing_left, .status-missing_right { color: var(--missing); }

    .twocol {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    pre {
      margin: 0;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      overflow: auto;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.83rem;
      min-height: 200px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .empty {
      color: var(--muted);
      padding: 8px;
      font-style: italic;
    }

    @media (max-width: 1100px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .panel {
        min-height: 300px;
      }
      .panel-body {
        height: auto;
        min-height: 220px;
      }
      .twocol {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>ReplayKit Local Diff UI</h1>
    <div class="sub">Inspect two local artifacts, jump to first divergence, and review step-level context.</div>

    <div class="controls">
      <div>
        <label for="leftArtifact">Left Artifact Path</label>
        <input id="leftArtifact" name="leftArtifact" list="artifactOptions" placeholder="examples/runs/m2_capture_boundaries.rpk" />
      </div>
      <div>
        <label for="rightArtifact">Right Artifact Path</label>
        <input id="rightArtifact" name="rightArtifact" list="artifactOptions" placeholder="examples/runs/m4_diverged_from_m2.rpk" />
      </div>
    </div>

    <datalist id="artifactOptions"></datalist>

    <div class="actions">
      <button id="loadButton" class="primary" aria-label="Load diff">Load Diff</button>
      <button id="jumpButton" aria-label="Jump to first divergence" disabled>Jump To First Divergence</button>
    </div>
    <div id="status" class="status" aria-live="polite"></div>
  </header>

  <main class="layout">
    <section class="panel" aria-labelledby="stepsHeading">
      <h2 id="stepsHeading">Steps</h2>
      <div class="panel-body">
        <ul id="stepList" class="steps"></ul>
        <div id="stepEmpty" class="empty">Load artifacts to view step statuses.</div>
      </div>
    </section>

    <section class="panel" aria-labelledby="changesHeading">
      <h2 id="changesHeading">Changes</h2>
      <div class="panel-body">
        <div class="twocol">
          <div>
            <h3>Left Value</h3>
            <pre id="leftValue">No step selected.</pre>
          </div>
          <div>
            <h3>Right Value</h3>
            <pre id="rightValue">No step selected.</pre>
          </div>
        </div>
      </div>
    </section>

    <section class="panel" aria-labelledby="metaHeading">
      <h2 id="metaHeading">Metadata</h2>
      <div class="panel-body">
        <pre id="metaPanel">No diff loaded.</pre>
      </div>
    </section>
  </main>

  <script>
    const state = {
      diff: null,
      selectedIndex: null,
      files: [],
    };

    const statusEl = document.getElementById("status");
    const leftInput = document.getElementById("leftArtifact");
    const rightInput = document.getElementById("rightArtifact");
    const optionsEl = document.getElementById("artifactOptions");
    const stepList = document.getElementById("stepList");
    const stepEmpty = document.getElementById("stepEmpty");
    const leftValue = document.getElementById("leftValue");
    const rightValue = document.getElementById("rightValue");
    const metaPanel = document.getElementById("metaPanel");
    const jumpButton = document.getElementById("jumpButton");

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.style.color = isError ? "#b91c1c" : "var(--muted)";
    }

    function pretty(value) {
      return JSON.stringify(value, null, 2);
    }

    function parseQueryDefaults() {
      const params = new URLSearchParams(window.location.search);
      const left = params.get("left");
      const right = params.get("right");
      if (left) leftInput.value = left;
      if (right) rightInput.value = right;
    }

    async function loadArtifactOptions() {
      try {
        const res = await fetch("/api/files");
        const data = await res.json();
        state.files = data.files || [];

        optionsEl.innerHTML = "";
        for (const file of state.files) {
          const option = document.createElement("option");
          option.value = file;
          optionsEl.appendChild(option);
        }

        if (!leftInput.value && state.files.length > 0) {
          leftInput.value = state.files[0];
        }
        if (!rightInput.value && state.files.length > 1) {
          rightInput.value = state.files[1];
        }

        if (state.files.length === 0) {
          setStatus("No local artifacts found in runs/ or examples/runs.", true);
        }
      } catch (_err) {
        setStatus("Failed to load local artifact list.", true);
      }
    }

    function renderStepDetails(stepDiff) {
      const leftMap = {};
      const rightMap = {};
      for (const change of stepDiff.changes || []) {
        leftMap[change.path] = change.left;
        rightMap[change.path] = change.right;
      }

      leftValue.textContent = Object.keys(leftMap).length ? pretty(leftMap) : "No changes in selected step.";
      rightValue.textContent = Object.keys(rightMap).length ? pretty(rightMap) : "No changes in selected step.";

      const meta = {
        index: stepDiff.index,
        status: stepDiff.status,
        left_step_id: stepDiff.left_step_id,
        right_step_id: stepDiff.right_step_id,
        left_type: stepDiff.left_type,
        right_type: stepDiff.right_type,
        context: stepDiff.context,
        change_count: (stepDiff.changes || []).length,
      };
      metaPanel.textContent = pretty(meta);
    }

    function selectStep(index) {
      state.selectedIndex = index;
      renderStepList();
      const step = state.diff.step_diffs[index];
      renderStepDetails(step);
    }

    function renderStepList() {
      stepList.innerHTML = "";
      if (!state.diff || !state.diff.step_diffs || state.diff.step_diffs.length === 0) {
        stepEmpty.style.display = "block";
        return;
      }

      stepEmpty.style.display = "none";
      state.diff.step_diffs.forEach((step, idx) => {
        const item = document.createElement("li");
        item.className = "step-item" + (state.selectedIndex === idx ? " active" : "");
        item.setAttribute("role", "button");
        item.setAttribute("tabindex", "0");

        const label = document.createElement("div");
        label.className = "step-status status-" + step.status;
        label.textContent = step.status;

        const title = document.createElement("div");
        title.textContent = "#" + step.index + " " + (step.left_type || step.right_type || "unknown");

        item.appendChild(label);
        item.appendChild(title);

        item.addEventListener("click", () => selectStep(idx));
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectStep(idx);
          }
        });

        stepList.appendChild(item);
      });
    }

    async function loadDiff() {
      const left = leftInput.value.trim();
      const right = rightInput.value.trim();

      if (!left || !right) {
        setStatus("Both artifact paths are required.", true);
        return;
      }

      setStatus("Loading diff...");

      try {
        const query = new URLSearchParams({ left, right });
        const res = await fetch("/api/diff?" + query.toString());
        const payload = await res.json();

        if (!res.ok) {
          setStatus(payload.error || "Failed to load diff", true);
          return;
        }

        state.diff = payload;
        const first = payload.first_divergence;
        jumpButton.disabled = !first;

        const summary = payload.summary || {};
        setStatus(
          "Loaded diff: identical=" + (summary.identical || 0) +
            " changed=" + (summary.changed || 0) +
            " missing_left=" + (summary.missing_left || 0) +
            " missing_right=" + (summary.missing_right || 0)
        );

        state.selectedIndex = 0;
        renderStepList();
        if (payload.step_diffs && payload.step_diffs.length > 0) {
          renderStepDetails(payload.step_diffs[0]);
        } else {
          leftValue.textContent = "No steps available.";
          rightValue.textContent = "No steps available.";
          metaPanel.textContent = pretty({
            left_path: payload.left_path,
            right_path: payload.right_path,
            identical: payload.identical,
          });
        }
      } catch (_err) {
        setStatus("Unable to fetch diff from local server.", true);
      }
    }

    function jumpToFirstDivergence() {
      if (!state.diff || !state.diff.first_divergence) {
        return;
      }
      const target = state.diff.first_divergence.index - 1;
      if (target >= 0) {
        selectStep(target);
      }
    }

    document.getElementById("loadButton").addEventListener("click", loadDiff);
    jumpButton.addEventListener("click", jumpToFirstDivergence);

    parseQueryDefaults();
    loadArtifactOptions();
  </script>
</body>
</html>
"""
