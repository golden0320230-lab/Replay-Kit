"""Passive listener daemon process for ReplayKit lifecycle commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from replaypack.artifact import write_artifact
from replaypack.core.models import Run, Step
from replaypack.listener_gateway import (
    build_best_effort_fallback_response,
    build_provider_response,
    detect_provider,
    normalize_provider_request,
    provider_request_fingerprint,
)
from replaypack.listener_agent_gateway import detect_agent, normalize_agent_events
from replaypack.listener_redaction import redact_listener_headers, redact_listener_value
from replaypack.listener_state import remove_listener_state, write_listener_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _ListenerRunRecorder:
    def __init__(
        self,
        *,
        session_id: str,
        out_path: Path,
        host: str,
        port: int,
    ) -> None:
        self._lock = threading.Lock()
        self._out_path = out_path
        self._step_sequence = 0
        self._request_sequence = 0
        self._agent_event_sequence = 0
        timestamp = _utc_now()
        self._run = Run(
            id=f"run-listener-{session_id}",
            timestamp=timestamp,
            source="listener",
            capture_mode="passive",
            listener_session_id=session_id,
            listener_process={
                "pid": os.getpid(),
                "executable": sys.executable,
                "command": list(sys.argv),
                "cwd": str(Path.cwd()),
            },
            listener_bind={"host": host, "port": port},
            environment_fingerprint={"listener_mode": "passive", "os": os.name},
            runtime_versions={
                "python": ".".join(
                    str(part) for part in sys.version_info[:3]
                ),
                "replaykit_listener": "1",
            },
            steps=[],
        )
        self._persist_locked()

    @property
    def out_path(self) -> Path:
        return self._out_path

    def record_provider_transaction(
        self,
        *,
        provider: str,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        fail_reason: str | None,
    ) -> tuple[int, dict[str, Any]]:
        with self._lock:
            self._request_sequence += 1
            request_id = (
                str(headers.get("x-request-id")).strip()
                if headers.get("x-request-id")
                else f"{provider}-request-{self._request_sequence:06d}"
            )
            request = normalize_provider_request(
                provider=provider,
                path=path,
                payload=payload,
                headers=headers,
                request_id=request_id,
            )
            correlation_id = provider_request_fingerprint(request)

            status_code, response_payload, normalized_response = build_provider_response(
                request=request,
                sequence=self._request_sequence,
                fail_reason=fail_reason,
            )

            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="model.request",
                    input={
                        "provider": provider,
                        "path": path,
                        "request_id": request.request_id,
                        "model": request.model,
                        "stream": request.stream,
                        "headers": redact_listener_headers(request.headers),
                        "payload": redact_listener_value(request.payload),
                    },
                    output={"status": "captured"},
                    metadata=redact_listener_value(
                        {
                            "provider": provider,
                            "path": path,
                            "request_id": request.request_id,
                            "correlation_id": correlation_id,
                            "capture_mode": "passive",
                        }
                    ),
                    timestamp=_utc_now(),
                )
            )
            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="model.response",
                    input=redact_listener_value({"request_id": request.request_id}),
                    output={
                        "status_code": status_code,
                        "output": redact_listener_value(normalized_response.response),
                        "assembled_text": redact_listener_value(
                            normalized_response.assembled_text
                        ),
                        "error": redact_listener_value(normalized_response.error),
                    },
                    metadata=redact_listener_value(
                        {
                            "provider": provider,
                            "path": path,
                            "request_id": request.request_id,
                            "correlation_id": correlation_id,
                            "capture_mode": "passive",
                        }
                    ),
                    timestamp=_utc_now(),
                )
            )
            self._persist_locked()
            return status_code, response_payload

    def record_agent_payload(
        self,
        *,
        agent: str,
        payload: Any,
    ) -> tuple[int, int]:
        with self._lock:
            normalized_events, dropped = normalize_agent_events(agent=agent, payload=payload)
            captured = 0
            for normalized_event in normalized_events:
                self._agent_event_sequence += 1
                request_id = normalized_event.get("request_id")
                if not request_id:
                    request_id = f"{agent}-event-{self._agent_event_sequence:06d}"
                metadata = dict(normalized_event["metadata"])
                metadata["request_id"] = request_id
                metadata["capture_mode"] = "passive"
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type=normalized_event["step_type"],
                        input=redact_listener_value(normalized_event["input"]),
                        output=redact_listener_value(normalized_event["output"]),
                        metadata=redact_listener_value(metadata),
                        timestamp=_utc_now(),
                    )
                )
                captured += 1

            if dropped > 0:
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type="error.event",
                        input={"agent": agent},
                        output={
                            "message": "dropped malformed or unsupported agent event frames",
                            "dropped": dropped,
                        },
                        metadata={
                            "agent": agent,
                            "event_type": "listener.drop",
                            "capture_mode": "passive",
                        },
                        timestamp=_utc_now(),
                    )
                )

            if captured > 0 or dropped > 0:
                self._persist_locked()
            return captured, dropped

    def record_internal_error(
        self,
        *,
        category: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="error.event",
                    input={"source": "listener", "category": category},
                    output={
                        "message": message,
                        "details": redact_listener_value(details or {}),
                    },
                    metadata={
                        "source": "listener",
                        "category": category,
                        "capture_mode": "passive",
                    },
                    timestamp=_utc_now(),
                )
            )
            try:
                self._persist_locked()
            except Exception:
                return

    def _next_step_id(self) -> str:
        self._step_sequence += 1
        return f"step-{self._step_sequence:06d}"

    def _persist_locked(self) -> None:
        write_artifact(
            self._run,
            self._out_path,
            metadata={
                "mode": "listener.passive",
                "listener_session_id": self._run.listener_session_id,
            },
        )


class _ReplayListenerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        session_id: str,
        state_file: Path,
        recorder: _ListenerRunRecorder | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.session_id = session_id
        self.state_file = state_file
        self.recorder = recorder
        self._metrics_lock = threading.Lock()
        self.capture_errors = 0
        self.dropped_events = 0
        self.degraded_responses = 0

    def register_capture_error(self) -> int:
        with self._metrics_lock:
            self.capture_errors += 1
            return self.capture_errors

    def register_dropped_events(self, count: int) -> int:
        with self._metrics_lock:
            self.dropped_events += max(0, count)
            return self.dropped_events

    def register_degraded_response(self) -> int:
        with self._metrics_lock:
            self.degraded_responses += 1
            return self.degraded_responses

    def metrics_payload(self) -> dict[str, int]:
        with self._metrics_lock:
            return {
                "capture_errors": self.capture_errors,
                "dropped_events": self.dropped_events,
                "degraded_responses": self.degraded_responses,
            }


class _ListenerHandler(BaseHTTPRequestHandler):
    server: _ReplayListenerServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        recorder = self.server.recorder
        if recorder is None:
            self._write_json(503, {"status": "error", "message": "recorder not ready"})
            return
        if parsed.path == "/health":
            self._write_json(
                200,
                {
                    "status": "ok",
                    "session_id": self.server.session_id,
                    "pid": os.getpid(),
                    "artifact_path": str(recorder.out_path),
                    "metrics": self.server.metrics_payload(),
                },
            )
            return
        self._write_json(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/shutdown":
            self._write_json(
                200,
                {"status": "ok", "message": "listener shutting down"},
            )

            def _shutdown() -> None:
                self.server.shutdown()

            threading.Thread(target=_shutdown, daemon=True).start()
            return

        agent = detect_agent(parsed.path)
        if agent is not None:
            recorder = self.server.recorder
            if recorder is None:
                self._write_json(503, {"status": "error", "message": "recorder not ready"})
                return
            payload, _parse_error = self._read_json_body()
            captured, dropped = recorder.record_agent_payload(
                agent=agent,
                payload=payload,
            )
            if dropped > 0:
                self.server.register_dropped_events(dropped)
            self._write_json(
                202,
                {
                    "status": "ok",
                    "agent": agent,
                    "captured": captured,
                    "dropped": dropped,
                    "metrics": self.server.metrics_payload(),
                },
            )
            return

        provider = detect_provider(parsed.path)
        if provider is None:
            self._write_json(404, {"status": "error", "message": "unsupported path"})
            return

        recorder = self.server.recorder
        if recorder is None:
            self._write_json(503, {"status": "error", "message": "recorder not ready"})
            return

        payload, parse_error = self._read_json_body()
        fail_reason = self.headers.get("x-replaykit-fail")
        if parse_error and not fail_reason:
            fail_reason = parse_error
        if not isinstance(payload, dict):
            if not fail_reason:
                fail_reason = "non_object_json_body"
            payload = {"raw_payload": payload}

        try:
            force_capture_fail = (
                str(self.headers.get("x-replaykit-capture-fail", "")).strip().lower()
                in {"1", "true", "yes"}
            )
            if force_capture_fail:
                raise RuntimeError("simulated capture failure")
            status_code, response_body = recorder.record_provider_transaction(
                provider=provider,
                path=parsed.path,
                payload=payload,
                headers={str(key): str(value) for key, value in self.headers.items()},
                fail_reason=fail_reason,
            )
        except Exception as error:
            capture_error_count = self.server.register_capture_error()
            degraded_sequence = self.server.register_degraded_response()
            recorder.record_internal_error(
                category="capture_failure",
                message="listener capture path failed; served degraded fallback response",
                details={
                    "provider": provider,
                    "path": parsed.path,
                    "error": str(error),
                    "capture_error_count": capture_error_count,
                },
            )
            status_code, response_body = build_best_effort_fallback_response(
                provider=provider,
                sequence=degraded_sequence,
            )
            self._write_json(status_code, response_body)
            return

        self._write_json(status_code, response_body)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> tuple[Any, str | None]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b""
        if not body:
            return {}, None
        decoded = body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            return {"raw_body": decoded}, "invalid_json_body"
        if isinstance(parsed, (dict, list)):
            return parsed, None
        return {"raw_body": decoded}, "non_object_json_body"

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m replaypack.listener_daemon",
        description="ReplayKit passive listener daemon process.",
    )
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--out",
        default=Path("runs/listener/listener-capture.rpk"),
        type=Path,
    )
    return parser


def _runtime_payload(
    *,
    session_id: str,
    host: str,
    port: int,
    out_path: Path,
) -> dict[str, Any]:
    return {
        "status": "running",
        "listener_session_id": session_id,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "artifact_path": str(out_path),
        "started_at": _utc_now(),
        "process": {
            "pid": os.getpid(),
            "executable": sys.executable,
            "command": list(sys.argv),
            "cwd": str(Path.cwd()),
        },
    }


def _startup_log_path(state_file: Path) -> Path:
    suffix = state_file.suffix or ".json"
    return state_file.with_suffix(f"{suffix}.startup.log")


def _append_startup_marker(state_file: Path, stage: str) -> None:
    path = _startup_log_path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_utc_now()} stage={stage}\n"
    path.write_text(
        (path.read_text(encoding="utf-8") if path.exists() else "") + line,
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    server: _ReplayListenerServer | None = None
    _append_startup_marker(args.state_file, "args.parsed")

    try:
        _append_startup_marker(args.state_file, "server.create.begin")
        server = _ReplayListenerServer(
            (args.host, args.port),
            _ListenerHandler,
            session_id=args.session_id,
            state_file=args.state_file,
            recorder=None,
        )
        _append_startup_marker(args.state_file, "server.create.ok")
    except OSError as error:
        _append_startup_marker(args.state_file, f"server.create.error:{error}")
        print(f"listener daemon failed: {error}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], int(server.server_address[1])
    _append_startup_marker(args.state_file, "recorder.create.begin")
    server.recorder = _ListenerRunRecorder(
        session_id=args.session_id,
        out_path=args.out,
        host=host,
        port=port,
    )
    _append_startup_marker(args.state_file, "recorder.create.ok")
    _append_startup_marker(args.state_file, "state.write.begin")
    write_listener_state(
        args.state_file,
        _runtime_payload(
            session_id=args.session_id,
            host=host,
            port=port,
            out_path=args.out,
        ),
    )
    _append_startup_marker(args.state_file, "state.write.ok")

    def _handle_signal(_signum: int, _frame: Any) -> None:
        if server is not None:
            server.shutdown()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        _append_startup_marker(args.state_file, "serve_forever.begin")
        server.serve_forever(poll_interval=0.2)
    finally:
        _append_startup_marker(args.state_file, "serve_forever.end")
        remove_listener_state(args.state_file)
        server.server_close()
        _append_startup_marker(args.state_file, "shutdown.complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
