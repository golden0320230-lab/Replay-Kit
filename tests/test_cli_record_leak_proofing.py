from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Iterator

import httpx
import requests
from typer.testing import CliRunner

from replaypack.capture.context import get_current_context
from replaypack.cli.app import app


@contextmanager
def _local_http_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_record_mode_uninstalls_interceptors_and_leaves_no_capture_context(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "wrapped.rpk"
    original_requests = requests.sessions.Session.request
    original_httpx_client = httpx.Client.request
    original_httpx_async = httpx.AsyncClient.request

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(out_path),
            "--",
            "python",
            "examples/apps/minimal_app.py",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_path.exists()

    assert requests.sessions.Session.request is original_requests
    assert httpx.Client.request is original_httpx_client
    assert httpx.AsyncClient.request is original_httpx_async
    assert get_current_context() is None

    with _local_http_server() as base_url:
        port = base_url.rsplit(":", 1)[1]
        response_requests = requests.get(f"{base_url}/post-capture", timeout=5)
        response_httpx = httpx.get(f"{base_url}/post-capture", timeout=5)
        response_httpx_localhost = httpx.get(
            f"http://localhost:{port}/post-capture-localhost",
            timeout=5,
        )

    assert response_requests.status_code == 200
    assert response_httpx.status_code == 200
    assert response_httpx_localhost.status_code == 200
    assert get_current_context() is None
