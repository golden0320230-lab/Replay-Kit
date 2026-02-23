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

from replaypack.listener_state import remove_listener_state, write_listener_state


class _ReplayListenerServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        session_id: str,
        state_file: Path,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.session_id = session_id
        self.state_file = state_file


class _ListenerHandler(BaseHTTPRequestHandler):
    server: _ReplayListenerServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self._write_json(
                200,
                {
                    "status": "ok",
                    "session_id": self.server.session_id,
                    "pid": os.getpid(),
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
        self._write_json(404, {"status": "error", "message": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

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
    return parser


def _runtime_payload(*, session_id: str, host: str, port: int) -> dict[str, Any]:
    return {
        "status": "running",
        "listener_session_id": session_id,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "process": {
            "pid": os.getpid(),
            "executable": sys.executable,
            "command": list(sys.argv),
            "cwd": str(Path.cwd()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    server: _ReplayListenerServer | None = None

    try:
        server = _ReplayListenerServer(
            (args.host, args.port),
            _ListenerHandler,
            session_id=args.session_id,
            state_file=args.state_file,
        )
    except OSError as error:
        print(f"listener daemon failed: {error}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], int(server.server_address[1])
    write_listener_state(
        args.state_file,
        _runtime_payload(
            session_id=args.session_id,
            host=host,
            port=port,
        ),
    )

    def _handle_signal(_signum: int, _frame: Any) -> None:
        if server is not None:
            server.shutdown()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        remove_listener_state(args.state_file)
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
