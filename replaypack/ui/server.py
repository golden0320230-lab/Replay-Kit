"""Local-first UI server for artifact diff inspection."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Iterator
from urllib.parse import parse_qs, quote, unquote, urlparse

from replaypack.artifact import ArtifactError, read_artifact
from replaypack.diff import diff_runs

_SUPPORTED_SUFFIXES = {".rpk", ".bundle"}


@dataclass(slots=True)
class UIServerConfig:
    host: str = "127.0.0.1"
    port: int = 4310
    base_dir: Path = Path.cwd()
    listener_recordings_dir: Path = Path("runs/passive/ui")
    listener_state_file: Path = Path("runs/passive/ui-listener-state.json")
    listener_out_file: Path = Path("runs/passive/ui-listener-capture.rpk")


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


def _resolve_runtime_path(base_dir: Path, configured: Path) -> Path:
    if configured.is_absolute():
        return configured
    return (base_dir / configured).resolve()


def _listener_capture_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"ui-listener-capture-{stamp}.rpk"


def _resolve_browser_path(base_dir: Path, raw_path: str | None) -> Path:
    if raw_path:
        candidate = Path(unquote(raw_path))
        target = candidate if candidate.is_absolute() else (base_dir / candidate)
    else:
        target = base_dir
    resolved = target.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {resolved}")
    return resolved


def _resolve_rename_paths(base_dir: Path, raw_path: str, new_name: str) -> tuple[Path, Path]:
    if not raw_path:
        raise ValueError("Missing required field: path")
    if not new_name:
        raise ValueError("Missing required field: new_name")
    if "/" in new_name or "\\" in new_name:
        raise ValueError("new_name must be a file name, not a path")
    if new_name in {".", ".."}:
        raise ValueError("new_name must be a valid file name")

    source_candidate = Path(unquote(raw_path))
    source = (
        source_candidate.resolve()
        if source_candidate.is_absolute()
        else (base_dir / source_candidate).resolve()
    )
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"File not found: {source}")
    if source.suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError("Only .rpk and .bundle files can be renamed from UI")

    target = source.with_name(new_name)
    if target == source:
        raise ValueError("new_name must differ from current file name")
    if target.suffix not in _SUPPORTED_SUFFIXES:
        raise ValueError("Renamed file must use .rpk or .bundle extension")
    if target.exists():
        raise FileExistsError(f"Destination already exists: {target}")
    return source, target


def _list_browser_entries(base_dir: Path, directory: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    children = sorted(
        directory.iterdir(),
        key=lambda item: (not item.is_dir(), item.name.lower()),
    )
    for child in children:
        display = _display_path(base_dir, child)
        entries.append(
            {
                "name": child.name,
                "path": display,
                "absolute_path": str(child),
                "is_dir": child.is_dir(),
                "size_bytes": child.stat().st_size if child.is_file() else None,
            }
        )
    return entries


def _run_listener_cli(base_dir: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    command = [sys.executable, "-m", "replaypack", "listen", *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=str(base_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    payload: dict[str, Any]
    if stdout:
        try:
            payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            payload = {
                "status": "error",
                "exit_code": completed.returncode,
                "message": stdout,
            }
    else:
        payload = {
            "status": "error",
            "exit_code": completed.returncode,
            "message": stderr or "listener command produced no output",
        }

    payload.setdefault("exit_code", completed.returncode)
    if completed.returncode != 0 and payload.get("status") == "ok":
        payload["status"] = "error"
    if stderr and "stderr" not in payload:
        payload["stderr"] = stderr
    return completed.returncode, payload


def create_ui_server(config: UIServerConfig) -> ThreadingHTTPServer:
    base_dir = config.base_dir.resolve()
    default_listener_state_path = _resolve_runtime_path(base_dir, config.listener_state_file)
    default_listener_out_path = _resolve_runtime_path(base_dir, config.listener_out_file)
    default_recordings_dir = _resolve_runtime_path(base_dir, config.listener_recordings_dir)

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

            if route == "/api/step":
                self._handle_step(query)
                return

            if route == "/api/fs/list":
                self._handle_fs_list(query)
                return

            if route == "/api/listener/status":
                self._handle_listener_status(query)
                return

            self._write_json(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            route = parsed.path

            if route == "/api/listener/start":
                self._handle_listener_start()
                return

            if route == "/api/listener/stop":
                self._handle_listener_stop()
                return

            if route == "/api/fs/rename":
                self._handle_fs_rename()
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

        def _handle_step(self, query: dict[str, list[str]]) -> None:
            left_raw = _first(query.get("left"))
            right_raw = _first(query.get("right"))
            index_raw = _first(query.get("index"))

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
            if not index_raw:
                self._write_json(400, {"error": "Missing required query param: index"})
                return

            try:
                index = _parse_step_index(index_raw)
                left_path = _resolve_artifact_path(base_dir, left_raw)
                right_path = _resolve_artifact_path(base_dir, right_raw)
                left_run = read_artifact(left_path)
                right_run = read_artifact(right_path)
                payload = {
                    "index": index,
                    "left_path": _display_path(base_dir, left_path),
                    "right_path": _display_path(base_dir, right_path),
                    "left_step": _step_payload_at_index(left_run.steps, index),
                    "right_step": _step_payload_at_index(right_run.steps, index),
                }
            except (FileNotFoundError, ArtifactError, ValueError) as error:
                self._write_json(400, {"error": str(error)})
                return
            self._write_json(200, payload)

        def _handle_fs_list(self, query: dict[str, list[str]]) -> None:
            raw_path = _first(query.get("path"))
            try:
                directory = _resolve_browser_path(base_dir, raw_path)
                parent = directory.parent if directory.parent != directory else None
                payload = {
                    "current_path": _display_path(base_dir, directory),
                    "current_absolute_path": str(directory),
                    "parent_path": _display_path(base_dir, parent) if parent else None,
                    "entries": _list_browser_entries(base_dir, directory),
                }
            except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as error:
                self._write_json(400, {"error": str(error)})
                return
            self._write_json(200, payload)

        def _handle_listener_status(self, query: dict[str, list[str]]) -> None:
            state_raw = _first(query.get("state_file"))
            listener_state_path = (
                _resolve_runtime_path(base_dir, Path(state_raw))
                if state_raw
                else default_listener_state_path
            )
            listener_out_path = default_listener_out_path
            listener_recordings_dir = default_recordings_dir
            code, payload = _run_listener_cli(
                base_dir,
                [
                    "status",
                    "--state-file",
                    str(listener_state_path),
                ],
            )
            payload["ui_listener_state_file"] = _display_path(base_dir, listener_state_path)
            payload["ui_listener_out_file"] = _display_path(base_dir, listener_out_path)
            payload["ui_listener_recordings_dir"] = _display_path(base_dir, listener_recordings_dir)
            self._write_json(200 if code == 0 else 400, payload)

        def _handle_listener_start(self) -> None:
            request = self._read_json_body()
            state_raw = str(request.get("state_file", "")).strip()
            recordings_raw = str(request.get("recordings_dir", "")).strip()
            out_raw = str(request.get("out_file", "")).strip()

            listener_state_path = (
                _resolve_runtime_path(base_dir, Path(state_raw))
                if state_raw
                else default_listener_state_path
            )
            listener_recordings_dir = (
                _resolve_runtime_path(base_dir, Path(recordings_raw))
                if recordings_raw
                else default_recordings_dir
            )
            if out_raw:
                listener_out_path = _resolve_runtime_path(base_dir, Path(out_raw))
            else:
                listener_out_path = listener_recordings_dir / _listener_capture_name()

            listener_state_path.parent.mkdir(parents=True, exist_ok=True)
            listener_recordings_dir.mkdir(parents=True, exist_ok=True)
            listener_out_path.parent.mkdir(parents=True, exist_ok=True)
            code, payload = _run_listener_cli(
                base_dir,
                [
                    "start",
                    "--state-file",
                    str(listener_state_path),
                    "--out",
                    str(listener_out_path),
                ],
            )
            payload["ui_listener_state_file"] = _display_path(base_dir, listener_state_path)
            payload["ui_listener_out_file"] = _display_path(base_dir, listener_out_path)
            payload["ui_listener_recordings_dir"] = _display_path(base_dir, listener_recordings_dir)
            self._write_json(200 if code == 0 else 400, payload)

        def _handle_listener_stop(self) -> None:
            request = self._read_json_body()
            state_raw = str(request.get("state_file", "")).strip()
            listener_state_path = (
                _resolve_runtime_path(base_dir, Path(state_raw))
                if state_raw
                else default_listener_state_path
            )
            listener_out_path = default_listener_out_path
            listener_recordings_dir = default_recordings_dir
            code, payload = _run_listener_cli(
                base_dir,
                [
                    "stop",
                    "--state-file",
                    str(listener_state_path),
                ],
            )
            payload["ui_listener_state_file"] = _display_path(base_dir, listener_state_path)
            payload["ui_listener_out_file"] = _display_path(base_dir, listener_out_path)
            payload["ui_listener_recordings_dir"] = _display_path(base_dir, listener_recordings_dir)
            self._write_json(200 if code == 0 else 400, payload)

        def _handle_fs_rename(self) -> None:
            request = self._read_json_body()
            source_raw = str(request.get("path", "")).strip()
            new_name_raw = str(request.get("new_name", "")).strip()
            try:
                source_path, target_path = _resolve_rename_paths(
                    base_dir,
                    source_raw,
                    new_name_raw,
                )
                source_path.rename(target_path)
            except (FileNotFoundError, ValueError, OSError) as error:
                self._write_json(400, {"status": "error", "message": str(error)})
                return

            self._write_json(
                200,
                {
                    "status": "ok",
                    "message": "File renamed.",
                    "old_path": _display_path(base_dir, source_path),
                    "new_path": _display_path(base_dir, target_path),
                    "old_absolute_path": str(source_path),
                    "new_absolute_path": str(target_path),
                },
            )

        def _read_json_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length")
            if not raw_length:
                return {}
            try:
                length = int(raw_length)
            except ValueError:
                return {}
            if length <= 0:
                return {}
            payload = self.rfile.read(length)
            if not payload:
                return {}
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            if not isinstance(data, dict):
                return {}
            return data

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


def _parse_step_index(raw_value: str) -> int:
    try:
        index = int(raw_value)
    except ValueError as error:
        raise ValueError("index must be a positive integer") from error
    if index <= 0:
        raise ValueError("index must be a positive integer")
    return index


def _step_payload_at_index(steps: list[Any], index: int) -> dict[str, Any] | None:
    array_index = index - 1
    if array_index < 0 or array_index >= len(steps):
        return None
    step = steps[array_index]
    if hasattr(step, "to_dict"):
        return step.to_dict()
    return None


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
      --surface: #f8f6f1;
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
      padding: 20px 24px 14px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 253, 250, 0.92);
      backdrop-filter: blur(2px);
    }

    h1 {
      margin: 0;
      font-size: 1.52rem;
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
      margin-top: 14px;
    }

    label {
      display: block;
      font-size: 0.85rem;
      margin-bottom: 6px;
      font-weight: 700;
    }

    input[type="text"] {
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
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }

    button {
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--ink);
      padding: 8px 12px;
      border-radius: 999px;
      cursor: pointer;
      font-weight: 700;
      font-size: 0.85rem;
    }

    button.primary {
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }

    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.84rem;
      padding: 4px 10px;
      border: 1px dashed var(--border);
      border-radius: 999px;
      background: #fff;
      margin: 0;
      font-weight: 600;
    }

    .toggle input {
      margin: 0;
    }

    .status {
      margin-top: 10px;
      min-height: 1.2em;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .layout {
      display: grid;
      grid-template-columns: 300px 1fr 360px;
      gap: 14px;
      padding: 16px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      min-height: 58vh;
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
      height: calc(58vh - 44px);
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
      transition: border-color 120ms ease;
    }

    .step-item:hover {
      border-color: #9ca3af;
    }

    .step-item.active {
      outline: 2px solid var(--accent);
    }

    .step-status {
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .status-identical { color: var(--identical); }
    .status-changed { color: var(--changed); }
    .status-missing_left, .status-missing_right { color: var(--missing); }

    .step-title {
      margin-top: 2px;
      font-size: 0.9rem;
      font-weight: 600;
    }

    .step-subline {
      margin-top: 4px;
      font-size: 0.78rem;
      color: var(--muted);
    }

    .changes-toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 8px;
    }

    .path-chip {
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 999px;
      padding: 6px 10px;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.76rem;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .change-list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 180px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
    }

    .change-item {
      border: 0;
      border-bottom: 1px solid #ece8df;
      padding: 8px 10px;
      margin: 0;
      background: transparent;
      cursor: pointer;
      text-align: left;
      border-radius: 0;
      width: 100%;
      font-weight: 600;
    }

    .change-item:last-child {
      border-bottom: 0;
    }

    .change-item.active {
      background: #eef7f5;
    }

    .change-item code {
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.77rem;
    }

    .change-item small {
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 0.75rem;
      font-weight: 500;
    }

    .tree-columns {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 10px;
    }

    .tree-shell {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      min-height: 240px;
      overflow: auto;
      padding: 8px;
    }

    .tree-shell h3 {
      margin: 0 0 6px;
      font-size: 0.8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }

    .raw-pre {
      min-height: 170px;
      font-size: 0.76rem;
    }

    .tree-node {
      margin: 3px 0;
      border-left: 2px solid #e5e2d8;
      padding-left: 8px;
    }

    .tree-node > summary {
      cursor: pointer;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.78rem;
      color: #374151;
      user-select: text;
    }

    .tree-children {
      margin-left: 6px;
      padding-left: 8px;
      border-left: 1px dashed #d9d5cb;
    }

    .tree-leaf {
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.78rem;
      margin: 3px 0;
      color: #1f2937;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .tree-key {
      color: #6b7280;
      margin-right: 4px;
    }

    pre {
      margin: 0;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      overflow: auto;
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.82rem;
      min-height: 230px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .empty {
      color: var(--muted);
      padding: 8px;
      font-style: italic;
    }

    .browser-toolbar {
      display: flex;
      gap: 8px;
      margin-top: 12px;
      margin-bottom: 8px;
      align-items: center;
      flex-wrap: wrap;
    }

    .browser-toolbar input[type="text"] {
      flex: 1 1 280px;
    }

    .browser-list {
      list-style: none;
      margin: 0;
      padding: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      max-height: 260px;
      overflow: auto;
    }

    .browser-item {
      padding: 8px 10px;
      border-bottom: 1px solid #ece8df;
      display: grid;
      gap: 6px;
    }

    .browser-item:last-child {
      border-bottom: 0;
    }

    .browser-path {
      font-family: "IBM Plex Mono", "Menlo", "Consolas", monospace;
      font-size: 0.78rem;
      word-break: break-word;
    }

    .browser-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }

    .browser-actions button {
      border-radius: 8px;
      padding: 5px 8px;
      font-size: 0.74rem;
    }

    .browser-meta {
      font-size: 0.75rem;
      color: var(--muted);
    }

    @media (max-width: 1200px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .panel {
        min-height: 320px;
      }
      .panel-body {
        height: auto;
        min-height: 230px;
      }
      .tree-columns {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>ReplayKit Local Diff UI</h1>
    <div class="sub">Inspect local artifacts with changed-only filtering, quick navigation, and collapsible JSON trees.</div>

    <div class="controls">
      <div>
        <label for="leftArtifact">Left Artifact Path</label>
        <input id="leftArtifact" name="leftArtifact" type="text" list="artifactOptions" placeholder="examples/runs/m2_capture_boundaries.rpk" />
      </div>
      <div>
        <label for="rightArtifact">Right Artifact Path</label>
        <input id="rightArtifact" name="rightArtifact" type="text" list="artifactOptions" placeholder="examples/runs/m4_diverged_from_m2.rpk" />
      </div>
    </div>

    <div class="controls">
      <div>
        <label for="listenerStateFile">Listener State File</label>
        <input id="listenerStateFile" name="listenerStateFile" type="text" placeholder="runs/passive/ui-listener-state.json" />
      </div>
      <div>
        <label for="listenerRecordingsDir">Default Recording Folder</label>
        <input id="listenerRecordingsDir" name="listenerRecordingsDir" type="text" placeholder="runs/passive/ui" />
      </div>
    </div>

    <div class="controls">
      <div>
        <label for="listenerOutFile">Output Artifact (optional; auto-generated if blank)</label>
        <input id="listenerOutFile" name="listenerOutFile" type="text" placeholder="runs/passive/ui/ui-listener-capture-YYYYMMDDTHHMMSSZ.rpk" />
      </div>
    </div>

    <datalist id="artifactOptions"></datalist>

    <div class="actions">
      <button id="loadButton" class="primary" aria-label="Load diff">Load Diff</button>
      <button id="listenerStartButton" aria-label="Start passive listener">Start Listening</button>
      <button id="listenerStopButton" aria-label="Stop passive listener">Stop Listening</button>
      <button id="listenerStatusButton" aria-label="Refresh passive listener status">Listener Status</button>
      <button id="jumpButton" aria-label="Jump to first divergence" disabled>Jump To First Divergence</button>
      <button id="prevStepButton" aria-label="Previous visible step" disabled>Prev Step</button>
      <button id="nextStepButton" aria-label="Next visible step" disabled>Next Step</button>
      <button id="prevChangedButton" aria-label="Previous changed step" disabled>Prev Changed</button>
      <button id="nextChangedButton" aria-label="Next changed step" disabled>Next Changed</button>
      <label class="toggle" for="changedOnlyToggle">
        <input id="changedOnlyToggle" type="checkbox" aria-label="Show changed steps only" />
        Changed Only
      </label>
    </div>
    <div id="status" class="status" aria-live="polite"></div>
  </header>

  <main class="layout">
    <section class="panel" aria-labelledby="stepsHeading">
      <h2 id="stepsHeading">Steps</h2>
      <div class="panel-body">
        <ul id="stepList" class="steps" aria-label="Diff step list"></ul>
        <div id="stepEmpty" class="empty">Load artifacts to view step statuses.</div>
      </div>
    </section>

    <section class="panel" aria-labelledby="changesHeading">
      <h2 id="changesHeading">Changes</h2>
      <div class="panel-body">
        <div class="changes-toolbar">
          <button id="prevFieldButton" aria-label="Previous changed field" disabled>Prev Field</button>
          <button id="nextFieldButton" aria-label="Next changed field" disabled>Next Field</button>
          <button id="copyPathButton" aria-label="Copy selected JSON path" disabled>Copy JSON Path</button>
          <div id="selectedPath" class="path-chip" title="Selected JSON path">No path selected.</div>
        </div>
        <ul id="changeList" class="change-list" aria-label="Field-level change list"></ul>
        <div id="changeEmpty" class="empty">Select a changed step to inspect field-level diffs.</div>
        <div class="tree-columns">
          <div class="tree-shell" aria-label="Left change JSON tree">
            <h3>Left</h3>
            <div id="leftTree"></div>
          </div>
          <div class="tree-shell" aria-label="Right change JSON tree">
            <h3>Right</h3>
            <div id="rightTree"></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel" aria-labelledby="metaHeading">
      <h2 id="metaHeading">Metadata</h2>
      <div class="panel-body">
        <pre id="metaPanel">No diff loaded.</pre>
        <div class="tree-columns">
          <div class="tree-shell" aria-label="Left selected step raw payload">
            <h3>Left Step Raw</h3>
            <pre id="leftStepRaw" class="raw-pre">No selected step.</pre>
          </div>
          <div class="tree-shell" aria-label="Right selected step raw payload">
            <h3>Right Step Raw</h3>
            <pre id="rightStepRaw" class="raw-pre">No selected step.</pre>
          </div>
        </div>
        <div class="browser-toolbar">
          <input id="browserPath" name="browserPath" type="text" placeholder="Browse path (absolute or relative to repo)" />
          <button id="browserOpenButton" aria-label="Open browser path">Open</button>
          <button id="browserUpButton" aria-label="Go to parent directory">Up</button>
          <button id="browserRefreshButton" aria-label="Refresh directory listing">Refresh</button>
        </div>
        <ul id="browserList" class="browser-list" aria-label="Filesystem browser list"></ul>
        <div id="browserEmpty" class="empty">Browse a directory to pick artifact files for left/right inputs.</div>
      </div>
    </section>
  </main>

  <script>
    const state = {
      diff: null,
      files: [],
      visibleStepIndexes: [],
      selectedVisibleStepIndex: null,
      selectedChangeIndex: null,
      browserCurrentPath: "",
      browserParentPath: "",
      selectedRawStepPayload: null,
    };

    const statusEl = document.getElementById("status");
    const leftInput = document.getElementById("leftArtifact");
    const rightInput = document.getElementById("rightArtifact");
    const listenerStateFileInput = document.getElementById("listenerStateFile");
    const listenerRecordingsDirInput = document.getElementById("listenerRecordingsDir");
    const listenerOutFileInput = document.getElementById("listenerOutFile");
    const optionsEl = document.getElementById("artifactOptions");
    const stepList = document.getElementById("stepList");
    const stepEmpty = document.getElementById("stepEmpty");
    const changeList = document.getElementById("changeList");
    const changeEmpty = document.getElementById("changeEmpty");
    const leftTree = document.getElementById("leftTree");
    const rightTree = document.getElementById("rightTree");
    const metaPanel = document.getElementById("metaPanel");
    const leftStepRaw = document.getElementById("leftStepRaw");
    const rightStepRaw = document.getElementById("rightStepRaw");
    const selectedPath = document.getElementById("selectedPath");
    const browserPathInput = document.getElementById("browserPath");
    const browserList = document.getElementById("browserList");
    const browserEmpty = document.getElementById("browserEmpty");
    const browserOpenButton = document.getElementById("browserOpenButton");
    const browserUpButton = document.getElementById("browserUpButton");
    const browserRefreshButton = document.getElementById("browserRefreshButton");
    const jumpButton = document.getElementById("jumpButton");
    const prevStepButton = document.getElementById("prevStepButton");
    const nextStepButton = document.getElementById("nextStepButton");
    const prevChangedButton = document.getElementById("prevChangedButton");
    const nextChangedButton = document.getElementById("nextChangedButton");
    const changedOnlyToggle = document.getElementById("changedOnlyToggle");
    const prevFieldButton = document.getElementById("prevFieldButton");
    const nextFieldButton = document.getElementById("nextFieldButton");
    const copyPathButton = document.getElementById("copyPathButton");
    const listenerStartButton = document.getElementById("listenerStartButton");
    const listenerStopButton = document.getElementById("listenerStopButton");
    const listenerStatusButton = document.getElementById("listenerStatusButton");

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.style.color = isError ? "#b91c1c" : "var(--muted)";
    }

    function pretty(value) {
      return JSON.stringify(value, null, 2);
    }

    function describeValue(value) {
      if (Array.isArray(value)) return "array(" + value.length + ")";
      if (value && typeof value === "object") return "object(" + Object.keys(value).length + ")";
      return typeof value;
    }

    function formatInline(value) {
      if (typeof value === "string") return JSON.stringify(value);
      if (value === undefined) return "undefined";
      return JSON.stringify(value);
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

    function formatBytes(value) {
      if (value === null || value === undefined) {
        return "-";
      }
      if (value < 1024) {
        return value + " B";
      }
      if (value < 1024 * 1024) {
        return (value / 1024).toFixed(1) + " KiB";
      }
      return (value / (1024 * 1024)).toFixed(1) + " MiB";
    }

    function setArtifactFromBrowser(side, path) {
      if (side === "left") {
        leftInput.value = path;
      } else {
        rightInput.value = path;
      }
      setStatus("Set " + side + " artifact path from browser: " + path);
    }

    function renderBrowserEntries(entries) {
      browserList.innerHTML = "";
      if (!entries || entries.length === 0) {
        browserEmpty.style.display = "block";
        return;
      }
      browserEmpty.style.display = "none";

      entries.forEach((entry) => {
        const item = document.createElement("li");
        item.className = "browser-item";

        const pathLine = document.createElement("div");
        pathLine.className = "browser-path";
        pathLine.textContent = entry.is_dir ? ("[dir] " + entry.path) : entry.path;
        item.appendChild(pathLine);

        const metaLine = document.createElement("div");
        metaLine.className = "browser-meta";
        metaLine.textContent = entry.is_dir ? "directory" : ("file • " + formatBytes(entry.size_bytes));
        item.appendChild(metaLine);

        const actions = document.createElement("div");
        actions.className = "browser-actions";

        if (entry.is_dir) {
          const openButton = document.createElement("button");
          openButton.type = "button";
          openButton.textContent = "Open";
          openButton.addEventListener("click", () => browseDirectory(entry.path));
          actions.appendChild(openButton);
        } else {
          const isArtifact = entry.path.endsWith(".rpk") || entry.path.endsWith(".bundle");

          const leftButton = document.createElement("button");
          leftButton.type = "button";
          leftButton.textContent = "Use Left";
          leftButton.disabled = !isArtifact;
          leftButton.addEventListener("click", () => setArtifactFromBrowser("left", entry.path));
          actions.appendChild(leftButton);

          const rightButton = document.createElement("button");
          rightButton.type = "button";
          rightButton.textContent = "Use Right";
          rightButton.disabled = !isArtifact;
          rightButton.addEventListener("click", () => setArtifactFromBrowser("right", entry.path));
          actions.appendChild(rightButton);

          const renameButton = document.createElement("button");
          renameButton.type = "button";
          renameButton.textContent = "Rename";
          renameButton.disabled = !isArtifact;
          renameButton.addEventListener("click", () => renameBrowserArtifact(entry.path, entry.name));
          actions.appendChild(renameButton);
        }
        item.appendChild(actions);
        browserList.appendChild(item);
      });
    }

    async function browseDirectory(path) {
      const query = new URLSearchParams();
      const target = (path || browserPathInput.value || "").trim();
      if (target) {
        query.set("path", target);
      }
      try {
        const res = await fetch("/api/fs/list" + (query.toString() ? ("?" + query.toString()) : ""));
        const payload = await res.json();
        if (!res.ok) {
          setStatus(payload.error || "Filesystem browse failed.", true);
          return;
        }
        state.browserCurrentPath = payload.current_path || "";
        state.browserParentPath = payload.parent_path || "";
        browserPathInput.value = state.browserCurrentPath || payload.current_absolute_path || "";
        browserUpButton.disabled = !state.browserParentPath;
        renderBrowserEntries(payload.entries || []);
      } catch (_err) {
        setStatus("Unable to fetch filesystem browser listing.", true);
      }
    }

    async function renameBrowserArtifact(path, currentName) {
      const proposedName = window.prompt("Rename artifact file", currentName || "");
      if (proposedName === null) {
        return;
      }
      const newName = proposedName.trim();
      if (!newName) {
        setStatus("Rename cancelled: new file name is required.", true);
        return;
      }
      try {
        const res = await fetch("/api/fs/rename", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: path, new_name: newName }),
        });
        const payload = await res.json();
        if (!res.ok || payload.status === "error") {
          setStatus(payload.message || "Rename failed.", true);
          return;
        }
        if (leftInput.value === payload.old_path) {
          leftInput.value = payload.new_path;
        }
        if (rightInput.value === payload.old_path) {
          rightInput.value = payload.new_path;
        }
        if (listenerOutFileInput.value === payload.old_path) {
          listenerOutFileInput.value = payload.new_path;
        }
        await loadArtifactOptions();
        await browseDirectory(state.browserCurrentPath || browserPathInput.value || "");
        setStatus((payload.message || "Rename completed.") + " " + payload.new_path);
      } catch (_err) {
        setStatus("Rename request failed.", true);
      }
    }

    function setListenerControlsDisabled(disabled) {
      listenerStartButton.disabled = disabled;
      listenerStopButton.disabled = disabled;
      listenerStatusButton.disabled = disabled;
      listenerStateFileInput.disabled = disabled;
      listenerRecordingsDirInput.disabled = disabled;
      listenerOutFileInput.disabled = disabled;
    }

    function refreshArtifactInputsFromListener(payload) {
      const outPath = payload ? (payload.artifact_out || payload.ui_listener_out_file) : null;
      const statePath = payload ? payload.ui_listener_state_file : null;
      const recordingsDir = payload ? payload.ui_listener_recordings_dir : null;
      if (statePath) {
        listenerStateFileInput.value = statePath;
      }
      if (recordingsDir) {
        listenerRecordingsDirInput.value = recordingsDir;
      }
      if (outPath) {
        listenerOutFileInput.value = outPath;
      }
      if (!outPath) {
        return;
      }
      if (!leftInput.value) {
        leftInput.value = outPath;
      }
      if (!rightInput.value) {
        rightInput.value = outPath;
      }
    }

    async function refreshListenerStatus() {
      setListenerControlsDisabled(true);
      try {
        const query = new URLSearchParams();
        const statePath = listenerStateFileInput.value.trim();
        if (statePath) {
          query.set("state_file", statePath);
        }
        const res = await fetch("/api/listener/status" + (query.toString() ? ("?" + query.toString()) : ""));
        const payload = await res.json();
        refreshArtifactInputsFromListener(payload);
        if (!res.ok || payload.status === "error") {
          setStatus(payload.message || "Listener status check failed.", true);
          return;
        }
        const running = payload.running ? "running" : "stopped";
        setStatus("Listener " + running + " (" + (payload.ui_listener_state_file || "state unknown") + ")");
      } catch (_err) {
        setStatus("Unable to fetch listener status from local server.", true);
      } finally {
        setListenerControlsDisabled(false);
      }
    }

    async function listenerAction(action) {
      setListenerControlsDisabled(true);
      setStatus(action === "start" ? "Starting listener..." : "Stopping listener...");
      try {
        const body = {
          state_file: listenerStateFileInput.value.trim(),
          recordings_dir: listenerRecordingsDirInput.value.trim(),
          out_file: listenerOutFileInput.value.trim(),
        };
        const res = await fetch("/api/listener/" + action, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await res.json();
        refreshArtifactInputsFromListener(payload);
        if (!res.ok || payload.status === "error") {
          setStatus(payload.message || ("Listener " + action + " failed."), true);
          return;
        }
        await loadArtifactOptions();
        setStatus(payload.message || ("Listener " + action + " completed."));
      } catch (_err) {
        setStatus("Listener " + action + " request failed.", true);
      } finally {
        setListenerControlsDisabled(false);
      }
    }

    function getVisibleStepIndexes() {
      if (!state.diff || !state.diff.step_diffs) {
        return [];
      }
      const onlyChanged = changedOnlyToggle.checked;
      const indexes = [];
      state.diff.step_diffs.forEach((step, idx) => {
        if (!onlyChanged || step.status !== "identical") {
          indexes.push(idx);
        }
      });
      return indexes;
    }

    function getChangedStepIndexes() {
      if (!state.diff || !state.diff.step_diffs) {
        return [];
      }
      const indexes = [];
      state.diff.step_diffs.forEach((step, idx) => {
        if (step.status !== "identical") {
          indexes.push(idx);
        }
      });
      return indexes;
    }

    function currentStepDiff() {
      if (!state.diff || state.selectedVisibleStepIndex === null) {
        return null;
      }
      const absoluteIndex = state.visibleStepIndexes[state.selectedVisibleStepIndex];
      if (absoluteIndex === undefined) {
        return null;
      }
      return state.diff.step_diffs[absoluteIndex];
    }

    function createTreeNode(label, value, depth) {
      const isObject = value !== null && typeof value === "object";
      if (!isObject) {
        const row = document.createElement("div");
        row.className = "tree-leaf";
        const key = document.createElement("span");
        key.className = "tree-key";
        key.textContent = label + ":";
        const val = document.createElement("span");
        val.textContent = " " + formatInline(value);
        row.appendChild(key);
        row.appendChild(val);
        return row;
      }

      const details = document.createElement("details");
      details.className = "tree-node";
      if (depth <= 1) {
        details.open = true;
      }

      const summary = document.createElement("summary");
      summary.textContent = label + " " + describeValue(value);
      details.appendChild(summary);

      const children = document.createElement("div");
      children.className = "tree-children";

      if (Array.isArray(value)) {
        if (value.length === 0) {
          children.appendChild(createTreeNode("(empty)", "", depth + 1));
        } else {
          value.forEach((item, idx) => {
            children.appendChild(createTreeNode("[" + idx + "]", item, depth + 1));
          });
        }
      } else {
        const keys = Object.keys(value).sort();
        if (keys.length === 0) {
          children.appendChild(createTreeNode("(empty)", "", depth + 1));
        } else {
          keys.forEach((key) => {
            children.appendChild(createTreeNode(key, value[key], depth + 1));
          });
        }
      }

      details.appendChild(children);
      return details;
    }

    function renderJsonTree(target, value, label) {
      target.innerHTML = "";
      target.appendChild(createTreeNode(label, value, 0));
    }

    function renderMetadata(stepDiff) {
      if (!state.diff) {
        metaPanel.textContent = "No diff loaded.";
        return;
      }

      const base = {
        left_path: state.diff.left_path,
        right_path: state.diff.right_path,
        summary: state.diff.summary,
        first_divergence_index: state.diff.first_divergence ? state.diff.first_divergence.index : null,
      };

      if (!stepDiff) {
        metaPanel.textContent = pretty(base);
        return;
      }

      const activeChange = (stepDiff.changes || [])[state.selectedChangeIndex || 0] || null;
      metaPanel.textContent = pretty({
        ...base,
        selected_step: {
          index: stepDiff.index,
          status: stepDiff.status,
          left_step_id: stepDiff.left_step_id,
          right_step_id: stepDiff.right_step_id,
          left_type: stepDiff.left_type,
          right_type: stepDiff.right_type,
          change_count: (stepDiff.changes || []).length,
          context: stepDiff.context,
        },
        selected_change_path: activeChange ? activeChange.path : null,
      });
    }

    function resetRawStepPanels(message) {
      const text = message || "No selected step.";
      leftStepRaw.textContent = text;
      rightStepRaw.textContent = text;
      state.selectedRawStepPayload = null;
    }

    function renderRawStepPayload(payload) {
      if (!payload) {
        resetRawStepPanels("No selected step.");
        return;
      }
      state.selectedRawStepPayload = payload;
      leftStepRaw.textContent = payload.left_step ? pretty(payload.left_step) : "Step not present on left artifact.";
      rightStepRaw.textContent = payload.right_step ? pretty(payload.right_step) : "Step not present on right artifact.";
    }

    async function loadRawStepPayload(stepIndex) {
      if (!state.diff || !stepIndex) {
        resetRawStepPanels("No selected step.");
        return;
      }
      try {
        const left = leftInput.value.trim();
        const right = rightInput.value.trim();
        if (!left || !right) {
          resetRawStepPanels("Both artifact paths are required.");
          return;
        }
        const query = new URLSearchParams({
          left: left,
          right: right,
          index: String(stepIndex),
        });
        const res = await fetch("/api/step?" + query.toString());
        const payload = await res.json();
        if (!res.ok) {
          resetRawStepPanels(payload.error || "Unable to load raw step payload.");
          return;
        }
        renderRawStepPayload(payload);
      } catch (_err) {
        resetRawStepPanels("Unable to load raw step payload.");
      }
    }

    function renderSelectedChange(stepDiff) {
      const changes = stepDiff.changes || [];
      if (!changes.length) {
        leftTree.innerHTML = "<div class='empty'>No change payload for this step.</div>";
        rightTree.innerHTML = "<div class='empty'>No change payload for this step.</div>";
        selectedPath.textContent = "No path selected.";
        return;
      }

      if (
        state.selectedChangeIndex === null ||
        state.selectedChangeIndex < 0 ||
        state.selectedChangeIndex >= changes.length
      ) {
        state.selectedChangeIndex = 0;
      }

      const active = changes[state.selectedChangeIndex];
      selectedPath.textContent = active.path;
      renderJsonTree(leftTree, active.left, "left");
      renderJsonTree(rightTree, active.right, "right");

      const buttons = changeList.querySelectorAll("button.change-item");
      buttons.forEach((button) => {
        const index = Number(button.dataset.changeIndex || "-1");
        if (index === state.selectedChangeIndex) {
          button.classList.add("active");
        } else {
          button.classList.remove("active");
        }
      });
    }

    function renderChangeList(stepDiff) {
      changeList.innerHTML = "";
      const changes = stepDiff.changes || [];
      if (!changes.length) {
        changeEmpty.style.display = "block";
        leftTree.innerHTML = "<div class='empty'>No selected change.</div>";
        rightTree.innerHTML = "<div class='empty'>No selected change.</div>";
        selectedPath.textContent = "No path selected.";
        return;
      }

      changeEmpty.style.display = "none";
      changes.forEach((change, idx) => {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.className = "change-item";
        button.type = "button";
        button.dataset.changeIndex = String(idx);
        button.setAttribute("aria-label", "Change path " + change.path);

        const code = document.createElement("code");
        code.textContent = change.path;
        const preview = document.createElement("small");
        preview.textContent = "left: " + formatInline(change.left) + " | right: " + formatInline(change.right);

        button.appendChild(code);
        button.appendChild(preview);
        button.addEventListener("click", () => {
          state.selectedChangeIndex = idx;
          renderSelectedChange(stepDiff);
          renderMetadata(stepDiff);
          updateNavigationButtons();
        });
        item.appendChild(button);
        changeList.appendChild(item);
      });

      renderSelectedChange(stepDiff);
    }

    function renderStepList() {
      stepList.innerHTML = "";
      const noDiff = !state.diff || !state.diff.step_diffs || state.diff.step_diffs.length === 0;
      if (noDiff) {
        stepEmpty.style.display = "block";
        return;
      }

      if (state.visibleStepIndexes.length === 0) {
        stepEmpty.style.display = "block";
        stepEmpty.textContent = "No steps match current filter.";
        return;
      }

      stepEmpty.style.display = "none";
      stepEmpty.textContent = "Load artifacts to view step statuses.";
      state.visibleStepIndexes.forEach((absoluteIndex, visibleIndex) => {
        const step = state.diff.step_diffs[absoluteIndex];
        const item = document.createElement("li");
        item.className = "step-item" + (state.selectedVisibleStepIndex === visibleIndex ? " active" : "");
        item.setAttribute("role", "button");
        item.setAttribute("tabindex", "0");
        item.setAttribute("aria-label", "Step " + step.index + " " + step.status);

        const label = document.createElement("div");
        label.className = "step-status status-" + step.status;
        label.textContent = step.status;

        const title = document.createElement("div");
        title.className = "step-title";
        title.textContent = "#" + step.index + " " + (step.left_type || step.right_type || "unknown");

        const subline = document.createElement("div");
        subline.className = "step-subline";
        subline.textContent = (step.changes || []).length + " field change(s)";

        item.appendChild(label);
        item.appendChild(title);
        item.appendChild(subline);

        item.addEventListener("click", () => selectStepByVisibleIndex(visibleIndex));
        item.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectStepByVisibleIndex(visibleIndex);
          }
        });

        stepList.appendChild(item);
      });
    }

    function updateNavigationButtons() {
      const hasDiff = !!state.diff;
      const hasVisible = state.visibleStepIndexes.length > 0;
      const hasSelectedStep = hasVisible && state.selectedVisibleStepIndex !== null;
      const selectedStep = currentStepDiff();
      const selectedChanges = selectedStep ? (selectedStep.changes || []) : [];

      jumpButton.disabled = !(hasDiff && state.diff.first_divergence);
      prevStepButton.disabled = !(hasSelectedStep && state.selectedVisibleStepIndex > 0);
      nextStepButton.disabled = !(
        hasSelectedStep && state.selectedVisibleStepIndex < state.visibleStepIndexes.length - 1
      );

      const changedSteps = getChangedStepIndexes();
      prevChangedButton.disabled = changedSteps.length === 0;
      nextChangedButton.disabled = changedSteps.length === 0;

      const selectedChange = state.selectedChangeIndex;
      prevFieldButton.disabled = !(selectedChanges.length > 1 && selectedChange !== null && selectedChange > 0);
      nextFieldButton.disabled = !(
        selectedChanges.length > 1 &&
        selectedChange !== null &&
        selectedChange < selectedChanges.length - 1
      );
      copyPathButton.disabled = !(selectedChanges.length > 0 && selectedChange !== null);
    }

    function selectStepByVisibleIndex(index) {
      if (index < 0 || index >= state.visibleStepIndexes.length) {
        return;
      }
      state.selectedVisibleStepIndex = index;
      state.selectedChangeIndex = 0;
      renderStepList();

      const step = currentStepDiff();
      if (!step) {
        changeList.innerHTML = "";
        leftTree.innerHTML = "<div class='empty'>No selected step.</div>";
        rightTree.innerHTML = "<div class='empty'>No selected step.</div>";
        selectedPath.textContent = "No path selected.";
        resetRawStepPanels("No selected step.");
        renderMetadata(null);
      } else {
        renderChangeList(step);
        renderMetadata(step);
        loadRawStepPayload(step.index);
      }

      updateNavigationButtons();
    }

    function selectStepByAbsoluteIndex(absoluteIndex) {
      const visibleIndex = state.visibleStepIndexes.indexOf(absoluteIndex);
      if (visibleIndex >= 0) {
        selectStepByVisibleIndex(visibleIndex);
        return;
      }

      changedOnlyToggle.checked = false;
      state.visibleStepIndexes = getVisibleStepIndexes();
      const fallbackIndex = state.visibleStepIndexes.indexOf(absoluteIndex);
      if (fallbackIndex >= 0) {
        selectStepByVisibleIndex(fallbackIndex);
      }
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
        state.visibleStepIndexes = getVisibleStepIndexes();
        state.selectedVisibleStepIndex = null;
        state.selectedChangeIndex = null;

        const summary = payload.summary || {};
        setStatus(
          "Loaded diff: identical=" + (summary.identical || 0) +
            " changed=" + (summary.changed || 0) +
            " missing_left=" + (summary.missing_left || 0) +
            " missing_right=" + (summary.missing_right || 0)
        );

        renderStepList();
        if (state.visibleStepIndexes.length > 0) {
          selectStepByVisibleIndex(0);
        } else {
          resetRawStepPanels("No selected step.");
          renderMetadata(null);
          updateNavigationButtons();
        }
      } catch (_err) {
        setStatus("Unable to fetch diff from local server.", true);
      }
    }

    function jumpToFirstDivergence() {
      if (!state.diff || !state.diff.first_divergence) {
        return;
      }
      const absoluteTarget = state.diff.first_divergence.index - 1;
      if (absoluteTarget >= 0) {
        selectStepByAbsoluteIndex(absoluteTarget);
      }
    }

    function stepNav(delta) {
      if (state.selectedVisibleStepIndex === null) {
        return;
      }
      selectStepByVisibleIndex(state.selectedVisibleStepIndex + delta);
    }

    function changedNav(delta) {
      const changed = getChangedStepIndexes();
      if (changed.length === 0) {
        return;
      }

      if (state.selectedVisibleStepIndex === null) {
        selectStepByAbsoluteIndex(changed[0]);
        return;
      }

      const currentAbsolute = state.visibleStepIndexes[state.selectedVisibleStepIndex];
      let currentPosition = changed.indexOf(currentAbsolute);

      if (currentPosition < 0) {
        if (delta > 0) {
          const next = changed.find((idx) => idx > currentAbsolute);
          selectStepByAbsoluteIndex(next !== undefined ? next : changed[0]);
          return;
        }
        const reversed = changed.slice().reverse();
        const prev = reversed.find((idx) => idx < currentAbsolute);
        selectStepByAbsoluteIndex(prev !== undefined ? prev : changed[changed.length - 1]);
        return;
      }

      currentPosition += delta;
      if (currentPosition < 0) {
        currentPosition = changed.length - 1;
      }
      if (currentPosition >= changed.length) {
        currentPosition = 0;
      }
      selectStepByAbsoluteIndex(changed[currentPosition]);
    }

    function changeNav(delta) {
      const step = currentStepDiff();
      if (!step) {
        return;
      }
      const changes = step.changes || [];
      if (changes.length === 0 || state.selectedChangeIndex === null) {
        return;
      }
      const target = state.selectedChangeIndex + delta;
      if (target < 0 || target >= changes.length) {
        return;
      }
      state.selectedChangeIndex = target;
      renderSelectedChange(step);
      renderMetadata(step);
      updateNavigationButtons();
    }

    async function copySelectedPath() {
      const step = currentStepDiff();
      if (!step || !step.changes || step.changes.length === 0 || state.selectedChangeIndex === null) {
        return;
      }
      const path = step.changes[state.selectedChangeIndex].path;

      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(path);
        } else {
          const temp = document.createElement("textarea");
          temp.value = path;
          document.body.appendChild(temp);
          temp.select();
          document.execCommand("copy");
          document.body.removeChild(temp);
        }
        setStatus("Copied JSON path: " + path);
      } catch (_err) {
        setStatus("Unable to copy JSON path from browser context.", true);
      }
    }

    function applyStepFilter() {
      const previousAbsolute =
        state.selectedVisibleStepIndex === null
          ? null
          : state.visibleStepIndexes[state.selectedVisibleStepIndex];

      state.visibleStepIndexes = getVisibleStepIndexes();
      if (state.visibleStepIndexes.length === 0) {
        state.selectedVisibleStepIndex = null;
        state.selectedChangeIndex = null;
        renderStepList();
        changeList.innerHTML = "";
        changeEmpty.style.display = "block";
        leftTree.innerHTML = "<div class='empty'>No selected step.</div>";
        rightTree.innerHTML = "<div class='empty'>No selected step.</div>";
        selectedPath.textContent = "No path selected.";
        resetRawStepPanels("No selected step.");
        renderMetadata(null);
        updateNavigationButtons();
        return;
      }

      if (previousAbsolute !== null) {
        const nextVisible = state.visibleStepIndexes.indexOf(previousAbsolute);
        state.selectedVisibleStepIndex = nextVisible >= 0 ? nextVisible : 0;
      } else {
        state.selectedVisibleStepIndex = 0;
      }

      selectStepByVisibleIndex(state.selectedVisibleStepIndex);
    }

    document.getElementById("loadButton").addEventListener("click", loadDiff);
    listenerStartButton.addEventListener("click", () => listenerAction("start"));
    listenerStopButton.addEventListener("click", () => listenerAction("stop"));
    listenerStatusButton.addEventListener("click", refreshListenerStatus);
    jumpButton.addEventListener("click", jumpToFirstDivergence);
    prevStepButton.addEventListener("click", () => stepNav(-1));
    nextStepButton.addEventListener("click", () => stepNav(1));
    prevChangedButton.addEventListener("click", () => changedNav(-1));
    nextChangedButton.addEventListener("click", () => changedNav(1));
    prevFieldButton.addEventListener("click", () => changeNav(-1));
    nextFieldButton.addEventListener("click", () => changeNav(1));
    copyPathButton.addEventListener("click", copySelectedPath);
    changedOnlyToggle.addEventListener("change", applyStepFilter);
    browserOpenButton.addEventListener("click", () => browseDirectory(browserPathInput.value));
    browserUpButton.addEventListener("click", () => {
      if (state.browserParentPath) {
        browseDirectory(state.browserParentPath);
      }
    });
    browserRefreshButton.addEventListener("click", () => browseDirectory(state.browserCurrentPath || browserPathInput.value));
    browserPathInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        browseDirectory(browserPathInput.value);
      }
    });

    parseQueryDefaults();
    loadArtifactOptions();
    refreshListenerStatus();
    browserUpButton.disabled = true;
    browseDirectory("");
  </script>
</body>
</html>
"""
