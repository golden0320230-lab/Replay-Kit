import asyncio
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Iterator

import httpx
import requests

from replaypack.capture import (
    InterceptionPolicy,
    capture_run,
    intercept_httpx,
    intercept_openai_like,
    intercept_requests,
)


@contextmanager
def _local_http_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ReplayPackTest/1.0"

        def do_POST(self) -> None:  # noqa: N802 - http.server naming convention
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length else b""

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "ok": True,
                "path": self.path,
                "body": body.decode("utf-8"),
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))

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


def test_requests_adapter_captures_http_and_restores_patch() -> None:
    original_request = requests.sessions.Session.request

    with _local_http_server() as base_url:
        with capture_run(
            run_id="run-adapter-requests-001",
            timestamp="2026-02-22T12:00:00Z",
            policy=InterceptionPolicy(capture_http_bodies=True),
        ) as context:
            with intercept_requests():
                response = requests.post(
                    f"{base_url}/requests",
                    json={"hello": "world"},
                    headers={"Authorization": "Bearer sk-requests-secret"},
                )
                assert response.status_code == 200

            run = context.to_run()

    assert requests.sessions.Session.request is original_request
    assert [step.type for step in run.steps] == ["tool.request", "tool.response"]
    assert run.steps[0].input["method"] == "POST"
    assert run.steps[0].metadata["adapter"] == "requests"
    assert run.steps[0].input["headers"]["Authorization"] == "[REDACTED]"
    assert run.steps[0].input["body"] == {"hello": "world"}
    assert run.steps[1].output["status_code"] == 200
    assert json.loads(run.steps[1].output["body"])["ok"] is True


def test_httpx_adapter_captures_sync_and_restores_patch() -> None:
    original_client_request = httpx.Client.request
    original_async_request = httpx.AsyncClient.request

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "path": request.url.path},
            headers={"X-Adapter": "httpx-sync"},
        )

    with capture_run(
        run_id="run-adapter-httpx-sync-001",
        timestamp="2026-02-22T12:00:10Z",
        policy=InterceptionPolicy(capture_http_bodies=True),
    ) as context:
        with intercept_httpx():
            transport = httpx.MockTransport(handler)
            with httpx.Client(transport=transport, base_url="https://example.local") as client:
                response = client.post(
                    "/sync",
                    json={"k": "v"},
                    headers={"Authorization": "Bearer sk-httpx-secret"},
                )
                assert response.status_code == 200

        run = context.to_run()

    assert httpx.Client.request is original_client_request
    assert httpx.AsyncClient.request is original_async_request
    assert [step.type for step in run.steps] == ["tool.request", "tool.response"]
    assert run.steps[0].input["method"] == "POST"
    assert run.steps[0].metadata["adapter"] == "httpx"
    assert run.steps[0].metadata["client"] == "sync"
    assert run.steps[0].input["headers"]["Authorization"] == "[REDACTED]"
    assert run.steps[0].input["body"] == {"k": "v"}
    assert json.loads(run.steps[1].output["body"])["path"] == "/sync"


def test_httpx_adapter_captures_async() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"ok": True, "path": request.url.path},
            headers={"X-Adapter": "httpx-async"},
        )

    async def scenario():
        with capture_run(
            run_id="run-adapter-httpx-async-001",
            timestamp="2026-02-22T12:00:20Z",
            policy=InterceptionPolicy(capture_http_bodies=True),
        ) as context:
            with intercept_httpx():
                transport = httpx.MockTransport(handler)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="https://example.local",
                ) as client:
                    response = await client.get(
                        "/async",
                        headers={"Authorization": "Bearer sk-httpx-async-secret"},
                    )
                    assert response.status_code == 201
            return context.to_run()

    run = asyncio.run(scenario())

    assert [step.type for step in run.steps] == ["tool.request", "tool.response"]
    assert run.steps[0].metadata["adapter"] == "httpx"
    assert run.steps[0].metadata["client"] == "async"
    assert run.steps[0].input["method"] == "GET"
    assert run.steps[0].input["headers"]["Authorization"] == "[REDACTED]"
    assert json.loads(run.steps[1].output["body"])["path"] == "/async"


def test_openai_like_adapter_captures_non_stream_and_streaming_assembly() -> None:
    class FakeCompletions:
        def create(self, **kwargs: object) -> object:
            if kwargs.get("stream"):
                def iterator():
                    yield {"choices": [{"delta": {"content": "Hel"}}]}
                    yield {"choices": [{"delta": {"content": "lo"}}]}

                return iterator()

            return {
                "id": "resp-001",
                "model": kwargs.get("model"),
                "content": "Hello",
            }

    original_create = FakeCompletions.create
    client = FakeCompletions()

    with capture_run(
        run_id="run-adapter-openai-like-001",
        timestamp="2026-02-22T12:00:30Z",
    ) as context:
        with intercept_openai_like(FakeCompletions, adapter_name="openai.chat.completions"):
            non_stream = client.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.1,
            )
            stream_chunks = list(
                client.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hello stream"}],
                    stream=True,
                )
            )

        run = context.to_run()

    assert FakeCompletions.create is original_create
    assert isinstance(non_stream, dict)
    assert non_stream["content"] == "Hello"
    assert len(stream_chunks) == 2

    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    assert run.steps[0].metadata["adapter"] == "openai.chat.completions"
    assert run.steps[1].output["output"]["content"] == "Hello"
    assert run.steps[2].metadata["stream"] is True
    assert run.steps[3].output["output"]["stream"] is True
    assert run.steps[3].output["output"]["assembled_text"] == "Hello"
