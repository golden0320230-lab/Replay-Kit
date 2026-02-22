"""Minimal local-only app used for ReplayKit record wrapper smoke tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import requests

from replaypack.capture import tool


@tool(name="example.echo")
def example_tool(value: str) -> dict[str, str]:
    return {"echo": value}


class _Handler(BaseHTTPRequestHandler):
    server_version = "ReplayKitExample/1.0"

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
        requests.get(f"{base_url}/requests", timeout=5)
        httpx.get(f"{base_url}/httpx", timeout=5)
        example_tool("hello")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
