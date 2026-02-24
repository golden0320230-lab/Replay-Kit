from contextlib import contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from typing import Any

import requests
from typer.testing import CliRunner
import zstandard as zstd

from replaypack.artifact import read_artifact
from replaypack.cli.app import app
from replaypack.listener_gateway import detect_provider


def _read_sse_events(response: requests.Response) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        events.append(json.loads(payload))
    return events


@contextmanager
def _local_upstream_server(
    routes: dict[str, tuple[int, dict[str, Any], float]],
) -> tuple[str, list[dict[str, Any]]]:
    captured_requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": {"type": "not_found", "path": self.path}}).encode("utf-8")
                )
                return

            status_code, response_payload, delay_seconds = route
            if delay_seconds > 0:
                time.sleep(delay_seconds)

            body_size = int(self.headers.get("Content-Length", "0"))
            body_bytes = self.rfile.read(body_size) if body_size else b"{}"
            decoded = body_bytes.decode("utf-8")
            try:
                parsed_payload = json.loads(decoded) if decoded else {}
            except json.JSONDecodeError:
                parsed_payload = {"_raw": decoded}
            captured_requests.append(
                {
                    "path": self.path,
                    "headers": {str(key).lower(): str(value) for key, value in self.headers.items()},
                    "payload": parsed_payload,
                }
            )

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{int(port)}", captured_requests
    finally:
        server.shutdown()
        thread.join(timeout=2.0)
        server.server_close()


def test_listener_gateway_detect_provider_paths() -> None:
    assert detect_provider("/responses") == "openai"
    assert detect_provider("/v1/responses") == "openai"
    assert detect_provider("/v1/chat/completions") == "openai"
    assert detect_provider("/v1/messages") == "anthropic"
    assert detect_provider("/v1beta/models/gemini-1.5-flash:generateContent") == "google"
    assert detect_provider("/v1/unknown") is None


def test_listener_gateway_serves_openai_models_routes(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        models = requests.get(
            f"{base_url}/models",
            params={"client_version": "0.104.0"},
            timeout=2.0,
        )
        assert models.status_code == 200
        payload = models.json()
        assert payload["object"] == "list"
        model_ids = {item["id"] for item in payload["data"]}
        assert "gpt-5.3-codex" in model_ids

        v1_models = requests.get(f"{base_url}/v1/models", timeout=2.0)
        assert v1_models.status_code == 200
        assert v1_models.json()["object"] == "list"
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert run.steps == []


def test_listener_gateway_captures_openai_anthropic_google_steps(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            timeout=2.0,
        )
        assert openai.status_code == 200

        anthropic = requests.post(
            f"{base_url}/v1/messages",
            json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]},
            timeout=2.0,
        )
        assert anthropic.status_code == 200

        google = requests.post(
            f"{base_url}/v1beta/models/gemini-1.5-flash:generateContent",
            json={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            timeout=2.0,
        )
        assert google.status_code == 200
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert run.source == "listener"
    assert run.capture_mode == "passive"
    assert run.listener_session_id == started["listener_session_id"]
    assert run.listener_bind == {"host": started["host"], "port": started["port"]}
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    providers = [step.metadata.get("provider") for step in run.steps]
    assert providers == ["openai", "openai", "anthropic", "anthropic", "google", "google"]


def test_listener_gateway_captures_openai_responses_routes(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        responses = requests.post(
            f"{base_url}/responses",
            json={"model": "gpt-5.3-codex", "input": "say hello"},
            timeout=2.0,
        )
        assert responses.status_code == 200
        responses_payload = responses.json()
        assert responses_payload["object"] == "response"
        assert responses_payload["status"] == "completed"
        assert responses_payload["output"][0]["type"] == "message"

        v1_responses = requests.post(
            f"{base_url}/v1/responses",
            json={"model": "gpt-5.3-codex", "input": "say hello again"},
            timeout=2.0,
        )
        assert v1_responses.status_code == 200
        v1_payload = v1_responses.json()
        assert v1_payload["object"] == "response"
        assert v1_payload["status"] == "completed"
        assert v1_payload["output"][0]["type"] == "message"
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    assert [step.metadata.get("provider") for step in run.steps] == [
        "openai",
        "openai",
        "openai",
        "openai",
    ]
    assert [step.metadata.get("path") for step in run.steps] == [
        "/responses",
        "/responses",
        "/v1/responses",
        "/v1/responses",
    ]
    response_steps = [step for step in run.steps if step.type == "model.response"]
    assert [step.output["assembled_text"] for step in response_steps] == [
        "ReplayKit listener response",
        "ReplayKit listener response",
    ]


def test_listener_gateway_decodes_zstd_encoded_openai_responses_payload(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        request_payload = {"model": "gpt-5.3-codex", "input": "say hello"}
        encoded_payload = zstd.ZstdCompressor(write_content_size=False).compress(
            json.dumps(request_payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        response = requests.post(
            f"{base_url}/responses",
            data=encoded_payload,
            headers={
                "content-type": "application/json",
                "content-encoding": "zstd",
            },
            timeout=2.0,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["object"] == "response"
        assert payload["status"] == "completed"
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert len(run.steps) == 2
    request_step = run.steps[0]
    assert request_step.type == "model.request"
    assert request_step.metadata.get("path") == "/responses"
    assert request_step.input["payload"]["model"] == "gpt-5.3-codex"
    assert request_step.input["payload"]["input"] == "say hello"


def test_listener_gateway_streams_openai_responses_sse_completion_event(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/responses",
            json={
                "model": "gpt-5.3-codex",
                "input": "say hello",
                "stream": True,
            },
            headers={"accept": "text/event-stream"},
            timeout=5.0,
            stream=True,
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/event-stream")
        events = _read_sse_events(response)
        event_types = [event.get("type") for event in events]
        assert "response.created" in event_types
        assert "response.completed" in event_types
        completed = [event for event in events if event.get("type") == "response.completed"][-1]
        assert completed["response"]["status"] == "completed"
        assert completed["response"]["output_text"] == "ReplayKit listener response"
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata.get("path") == "/responses"
    assert run.steps[1].output["stream"]["enabled"] is True


def test_listener_gateway_reports_unsupported_content_encoding(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/responses",
            data=json.dumps({"model": "gpt-5.3-codex", "input": "say hello"}).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "content-encoding": "br",
            },
            timeout=2.0,
        )
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["type"] == "listener_gateway_error"
        assert "unsupported_content_encoding:br" in body["error"]["message"]
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[-1].output["status_code"] == 502


def test_listener_gateway_error_path_returns_502_and_captures_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"x-replaykit-fail": "forced-failure"},
            timeout=2.0,
        )
        assert response.status_code == 502
        body = response.json()
        assert body["error"]["type"] == "listener_gateway_error"
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    response_step = run.steps[-1]
    assert response_step.output["status_code"] == 502
    assert response_step.output["error"] == {
        "message": "forced-failure",
        "type": "gateway_error",
    }


def test_listener_gateway_forwards_upstream_provider_responses(tmp_path: Path) -> None:
    routes = {
        "/v1/chat/completions": (
            200,
            {
                "id": "chatcmpl-upstream-001",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "openai-upstream"}}],
            },
            0.0,
        ),
        "/v1/messages": (
            200,
            {
                "id": "msg-upstream-001",
                "type": "message",
                "content": [{"type": "text", "text": "anthropic-upstream"}],
            },
            0.0,
        ),
        "/v1beta/models/gemini-1.5-flash:generateContent": (
            200,
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "google-upstream"}],
                        }
                    }
                ]
            },
            0.0,
        ),
    }
    with _local_upstream_server(routes) as (upstream_base_url, captured_requests):
        runner = CliRunner()
        state_file = tmp_path / "listener-state.json"
        out_path = tmp_path / "listener-capture.rpk"
        start_result = runner.invoke(
            app,
            [
                "listen",
                "start",
                "--state-file",
                str(state_file),
                "--out",
                str(out_path),
                "--json",
            ],
            env={
                "REPLAYKIT_OPENAI_UPSTREAM_URL": upstream_base_url,
                "REPLAYKIT_ANTHROPIC_UPSTREAM_URL": upstream_base_url,
                "REPLAYKIT_GEMINI_UPSTREAM_URL": upstream_base_url,
            },
        )
        assert start_result.exit_code == 0, start_result.output
        started = json.loads(start_result.stdout.strip())
        base_url = f"http://{started['host']}:{started['port']}"
        try:
            openai = requests.post(
                f"{base_url}/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi openai"}]},
                timeout=2.0,
            )
            assert openai.status_code == 200
            assert openai.json() == routes["/v1/chat/completions"][1]

            anthropic = requests.post(
                f"{base_url}/v1/messages",
                json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi anthropic"}]},
                timeout=2.0,
            )
            assert anthropic.status_code == 200
            assert anthropic.json() == routes["/v1/messages"][1]

            google = requests.post(
                f"{base_url}/v1beta/models/gemini-1.5-flash:generateContent",
                json={"contents": [{"role": "user", "parts": [{"text": "hi google"}]}]},
                timeout=2.0,
            )
            assert google.status_code == 200
            assert google.json() == routes["/v1beta/models/gemini-1.5-flash:generateContent"][1]
        finally:
            stop_result = runner.invoke(
                app,
                [
                    "listen",
                    "stop",
                    "--state-file",
                    str(state_file),
                    "--json",
                ],
            )
            assert stop_result.exit_code == 0, stop_result.output

    assert [entry["path"] for entry in captured_requests] == [
        "/v1/chat/completions",
        "/v1/messages",
        "/v1beta/models/gemini-1.5-flash:generateContent",
    ]
    assert captured_requests[0]["payload"]["messages"][0]["content"] == "hi openai"
    assert captured_requests[1]["payload"]["messages"][0]["content"] == "hi anthropic"
    assert captured_requests[2]["payload"]["contents"][0]["parts"][0]["text"] == "hi google"

    run = read_artifact(out_path)
    response_steps = [step for step in run.steps if step.type == "model.response"]
    assert [step.output["status_code"] for step in response_steps] == [200, 200, 200]
    assert response_steps[0].output["output"] == routes["/v1/chat/completions"][1]
    assert response_steps[1].output["output"] == routes["/v1/messages"][1]
    assert response_steps[2].output["output"] == routes["/v1beta/models/gemini-1.5-flash:generateContent"][1]
    assert response_steps[0].output["assembled_text"] == "openai-upstream"
    assert response_steps[1].output["assembled_text"] == "anthropic-upstream"
    assert response_steps[2].output["assembled_text"] == "google-upstream"


def test_listener_gateway_forwards_upstream_openai_responses_routes(tmp_path: Path) -> None:
    routes = {
        "/responses": (
            200,
            {
                "id": "resp-upstream-001",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.3-codex",
                "output": [
                    {
                        "id": "msg-upstream-001",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hi from upstream"}],
                    }
                ],
            },
            0.0,
        ),
        "/v1/responses": (
            200,
            {
                "id": "resp-upstream-002",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.3-codex",
                "output": [
                    {
                        "id": "msg-upstream-002",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hello from upstream"}],
                    }
                ],
            },
            0.0,
        ),
    }
    with _local_upstream_server(routes) as (upstream_base_url, captured_requests):
        runner = CliRunner()
        state_file = tmp_path / "listener-state.json"
        out_path = tmp_path / "listener-capture.rpk"
        start_result = runner.invoke(
            app,
            [
                "listen",
                "start",
                "--state-file",
                str(state_file),
                "--out",
                str(out_path),
                "--json",
            ],
            env={
                "REPLAYKIT_OPENAI_UPSTREAM_URL": upstream_base_url,
            },
        )
        assert start_result.exit_code == 0, start_result.output
        started = json.loads(start_result.stdout.strip())
        base_url = f"http://{started['host']}:{started['port']}"
        try:
            responses = requests.post(
                f"{base_url}/responses",
                json={"model": "gpt-5.3-codex", "input": "hello"},
                timeout=2.0,
            )
            assert responses.status_code == 200
            assert responses.json() == routes["/responses"][1]

            v1_responses = requests.post(
                f"{base_url}/v1/responses",
                json={"model": "gpt-5.3-codex", "input": "hello again"},
                timeout=2.0,
            )
            assert v1_responses.status_code == 200
            assert v1_responses.json() == routes["/v1/responses"][1]
        finally:
            stop_result = runner.invoke(
                app,
                [
                    "listen",
                    "stop",
                    "--state-file",
                    str(state_file),
                    "--json",
                ],
            )
            assert stop_result.exit_code == 0, stop_result.output

    assert [entry["path"] for entry in captured_requests] == [
        "/responses",
        "/v1/responses",
    ]
    assert captured_requests[0]["payload"]["input"] == "hello"
    assert captured_requests[1]["payload"]["input"] == "hello again"

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    response_steps = [step for step in run.steps if step.type == "model.response"]
    assert [step.output["status_code"] for step in response_steps] == [200, 200]
    assert response_steps[0].output["output"] == routes["/responses"][1]
    assert response_steps[1].output["output"] == routes["/v1/responses"][1]
    assert response_steps[0].output["assembled_text"] == "hi from upstream"
    assert response_steps[1].output["assembled_text"] == "hello from upstream"
    assert response_steps[0].metadata.get("response_source") == "upstream"
    assert response_steps[1].metadata.get("response_source") == "upstream"


def test_listener_gateway_passes_upstream_non_2xx_status_and_body(tmp_path: Path) -> None:
    upstream_error_body = {
        "error": {
            "type": "rate_limit_error",
            "message": "too many requests",
        }
    }
    with _local_upstream_server(
        {
            "/v1/chat/completions": (
                429,
                upstream_error_body,
                0.0,
            )
        }
    ) as (upstream_base_url, _captured_requests):
        runner = CliRunner()
        state_file = tmp_path / "listener-state.json"
        out_path = tmp_path / "listener-capture.rpk"
        start_result = runner.invoke(
            app,
            [
                "listen",
                "start",
                "--state-file",
                str(state_file),
                "--out",
                str(out_path),
                "--json",
            ],
            env={"REPLAYKIT_OPENAI_UPSTREAM_URL": upstream_base_url},
        )
        assert start_result.exit_code == 0, start_result.output
        started = json.loads(start_result.stdout.strip())
        base_url = f"http://{started['host']}:{started['port']}"
        try:
            response = requests.post(
                f"{base_url}/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
                timeout=2.0,
            )
            assert response.status_code == 429
            assert response.json() == upstream_error_body
        finally:
            stop_result = runner.invoke(
                app,
                [
                    "listen",
                    "stop",
                    "--state-file",
                    str(state_file),
                    "--json",
                ],
            )
            assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    response_step = run.steps[-1]
    assert response_step.type == "model.response"
    assert response_step.output["status_code"] == 429
    assert response_step.output["output"] == upstream_error_body
    assert response_step.output["error"] == {
        "payload": upstream_error_body,
        "status_code": 429,
    }
    assert response_step.metadata.get("response_source") == "upstream"


def test_listener_gateway_upstream_timeout_returns_502(tmp_path: Path) -> None:
    with _local_upstream_server(
        {
            "/v1/chat/completions": (
                200,
                {
                    "id": "chatcmpl-upstream-timeout",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "slow"}}],
                },
                0.25,
            )
        }
    ) as (upstream_base_url, _captured_requests):
        runner = CliRunner()
        state_file = tmp_path / "listener-state.json"
        out_path = tmp_path / "listener-capture.rpk"
        start_result = runner.invoke(
            app,
            [
                "listen",
                "start",
                "--state-file",
                str(state_file),
                "--out",
                str(out_path),
                "--json",
            ],
            env={
                "REPLAYKIT_OPENAI_UPSTREAM_URL": upstream_base_url,
                "REPLAYKIT_LISTENER_UPSTREAM_TIMEOUT_SECONDS": "0.05",
            },
        )
        assert start_result.exit_code == 0, start_result.output
        started = json.loads(start_result.stdout.strip())
        base_url = f"http://{started['host']}:{started['port']}"
        try:
            response = requests.post(
                f"{base_url}/v1/chat/completions",
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "timeout"}]},
                timeout=2.0,
            )
            assert response.status_code == 502
            body = response.json()
            assert body["error"]["type"] == "listener_gateway_error"
            assert "upstream_forward_failed" in body["error"]["message"]
        finally:
            stop_result = runner.invoke(
                app,
                [
                    "listen",
                    "stop",
                    "--state-file",
                    str(state_file),
                    "--json",
                ],
            )
            assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    response_step = run.steps[-1]
    assert response_step.output["status_code"] == 502
    assert response_step.output["error"]["type"] == "gateway_error"
    assert "upstream_forward_failed" in response_step.output["error"]["message"]
    assert response_step.metadata.get("response_source") == "upstream_error"


def test_listener_gateway_stream_capture_records_ordered_events(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        responses_route = requests.post(
            f"{base_url}/responses",
            json={
                "model": "gpt-5.3-codex",
                "stream": True,
                "input": "hello responses stream",
            },
            timeout=2.0,
        )
        assert responses_route.status_code == 200

        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hello openai"}],
            },
            timeout=2.0,
        )
        assert openai.status_code == 200

        anthropic = requests.post(
            f"{base_url}/v1/messages",
            json={
                "model": "claude-3-5-sonnet",
                "stream": True,
                "messages": [{"role": "user", "content": "hello anthropic"}],
            },
            timeout=2.0,
        )
        assert anthropic.status_code == 200

        google = requests.post(
            f"{base_url}/v1beta/models/gemini-1.5-flash:generateContent",
            json={
                "stream": True,
                "contents": [{"role": "user", "parts": [{"text": "hello google"}]}],
            },
            timeout=2.0,
        )
        assert google.status_code == 200
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    response_steps = [step for step in run.steps if step.type == "model.response"]
    assert len(response_steps) == 4

    for step in response_steps:
        stream_payload = step.output["stream"]
        assert stream_payload["enabled"] is True
        assert stream_payload["completed"] is True
        assert stream_payload["event_count"] > 0
        events = stream_payload["events"]
        assert [event["index"] for event in events] == list(
            range(1, len(events) + 1)
        )
        assembled = "".join(event["delta_text"] for event in events)
        assert assembled == step.output["assembled_text"]


def test_listener_gateway_stream_failure_marks_incomplete_stream(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={"x-replaykit-fail": "forced-stream-failure"},
            timeout=2.0,
        )
        assert response.status_code == 502
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    response_step = run.steps[-1]
    assert response_step.type == "model.response"
    assert response_step.output["status_code"] == 502
    stream_payload = response_step.output["stream"]
    assert stream_payload["enabled"] is True
    assert stream_payload["completed"] is False
    assert stream_payload["event_count"] == 0
    assert stream_payload["events"] == []
    assert response_step.output["error"]["type"] == "gateway_error"


def test_listener_gateway_responses_stream_failure_marks_incomplete_stream(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    out_path = tmp_path / "listener-capture.rpk"

    start_result = runner.invoke(
        app,
        [
            "listen",
            "start",
            "--state-file",
            str(state_file),
            "--out",
            str(out_path),
            "--json",
        ],
    )
    assert start_result.exit_code == 0, start_result.output
    started = json.loads(start_result.stdout.strip())
    base_url = f"http://{started['host']}:{started['port']}"

    try:
        response = requests.post(
            f"{base_url}/responses",
            json={
                "model": "gpt-5.3-codex",
                "stream": True,
                "input": "hello",
            },
            headers={"x-replaykit-fail": "forced-stream-failure"},
            timeout=2.0,
        )
        assert response.status_code == 502
    finally:
        stop_result = runner.invoke(
            app,
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
        )
        assert stop_result.exit_code == 0, stop_result.output

    run = read_artifact(out_path)
    response_step = run.steps[-1]
    assert response_step.type == "model.response"
    assert response_step.output["status_code"] == 502
    stream_payload = response_step.output["stream"]
    assert stream_payload["enabled"] is True
    assert stream_payload["completed"] is False
    assert stream_payload["event_count"] == 0
    assert stream_payload["events"] == []
    assert response_step.output["error"]["type"] == "gateway_error"
