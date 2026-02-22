from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Iterator

import pytest
import replaykit
import requests

from replaypack.artifact import read_artifact
from replaypack.replay import ReplayConfig, replay_stub_run


@contextmanager
def _local_http_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

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


def test_public_tool_decorator_captures_io_and_order_with_http(tmp_path: Path) -> None:
    @replaykit.tool(name="public.multiply")
    def multiply(left: int, right: int) -> dict[str, int]:
        return {"product": left * right}

    out_path = tmp_path / "tool-http-order.rpk"
    with _local_http_server() as base_url:
        with replaykit.record(
            out_path,
            intercept=("requests",),
            run_id="run-tool-order",
            timestamp="2026-02-22T21:00:00Z",
        ):
            requests.get(f"{base_url}/http", timeout=5)
            result = multiply(3, 4)

    assert result == {"product": 12}
    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == [
        "tool.request",
        "tool.response",
        "tool.request",
        "tool.response",
    ]
    assert run.steps[0].metadata["boundary"] == "http"
    assert run.steps[1].metadata["boundary"] == "http"
    assert run.steps[2].metadata["boundary"] == "tool"
    assert run.steps[2].metadata["tool"] == "public.multiply"
    assert run.steps[2].input["args"] == [3, 4]
    assert run.steps[3].output["result"] == {"product": 12}


def test_public_tool_decorator_records_structured_error_events(tmp_path: Path) -> None:
    @replaykit.tool(name="public.explode")
    def explode(text: str) -> None:
        raise RuntimeError(f"boom:{text}")

    out_path = tmp_path / "tool-error.rpk"
    with pytest.raises(RuntimeError, match="boom:bad"):
        with replaykit.record(
            out_path,
            intercept=("requests",),
            run_id="run-tool-error",
            timestamp="2026-02-22T21:10:00Z",
        ):
            explode("bad")

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["tool.request", "error.event"]
    error_step = run.steps[1]
    assert error_step.metadata["boundary"] == "tool"
    assert error_step.metadata["kind"] == "runtime"
    assert error_step.output["error_type"] == "RuntimeError"
    assert "boom:bad" in error_step.output["message"]


def test_tool_steps_replay_offline_in_stub_mode(tmp_path: Path) -> None:
    @replaykit.tool(name="public.echo")
    def echo(text: str) -> dict[str, str]:
        return {"echo": text}

    source_path = tmp_path / "tool-source.rpk"
    with replaykit.record(
        source_path,
        intercept=("requests",),
        run_id="run-tool-replay",
        timestamp="2026-02-22T21:20:00Z",
    ):
        echo("offline")

    source = read_artifact(source_path)
    replayed = replay_stub_run(
        source,
        config=ReplayConfig(seed=7, fixed_clock="2026-02-22T21:21:00Z"),
    )

    assert len(replayed.steps) == len(source.steps)
    assert replayed.steps[0].metadata["boundary"] == "tool"
    assert replayed.steps[1].metadata["boundary"] == "tool"
    assert replayed.steps[1].output["result"] == {"echo": "offline"}
