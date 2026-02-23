"""Minimal local-only target app for replaykit record target mode demos."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import requests


class _Handler(BaseHTTPRequestHandler):
    server_version = "ReplayKitTargetExample/1.0"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = {"ok": True, "path": self.path}
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        requests.get(f"{base_url}/target/requests", timeout=5)
        httpx.get(f"{base_url}/target/httpx", timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
