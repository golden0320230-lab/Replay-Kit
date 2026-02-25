import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import requests
from typer.testing import CliRunner
import zstandard as zstd

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def _read_sse_events(response: requests.Response) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        events.append(json.loads(payload))
    return events


def _start_listener(runner: CliRunner, *, state_file: Path, out_path: Path) -> tuple[str, int]:
    start = runner.invoke(
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
    assert start.exit_code == 0, start.output
    payload = json.loads(start.stdout.strip())
    return str(payload["host"]), int(payload["port"])


def _stop_listener(runner: CliRunner, *, state_file: Path) -> None:
    stop = runner.invoke(
        app,
        [
            "listen",
            "stop",
            "--state-file",
            str(state_file),
            "--json",
        ],
    )
    assert stop.exit_code == 0, stop.output


@contextmanager
def _fake_openai_upstream() -> str:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/responses", "/v1/responses"}:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"unsupported path"}')
                return
            body = {
                "id": "resp-upstream-000001",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.3-codex",
                "output": [
                    {
                        "id": "fc-upstream-000001",
                        "type": "function_call",
                        "name": "shell",
                        "call_id": "call-upstream-000001",
                        "arguments": '{"command":"echo hi"}',
                    },
                    {
                        "id": "msg-upstream-000001",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "done",
                                "annotations": [],
                            }
                        ],
                    },
                ],
                "output_text": "done",
            }
            payload = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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


def test_passive_listener_e2e_non_stream_capture_replay_assert(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-state.json"
    capture_path = tmp_path / "listener-capture.rpk"
    replay_path = tmp_path / "listener-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            timeout=2.0,
        )
        assert openai.status_code == 200

        anthropic = requests.post(
            f"{base_url}/v1/messages",
            json={"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hello"}]},
            timeout=2.0,
        )
        assert anthropic.status_code == 200
    finally:
        _stop_listener(runner, state_file=state_file)

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    source_run = read_artifact(capture_path)
    replay_run = read_artifact(replay_path)
    assert [step.type for step in source_run.steps] == [step.type for step in replay_run.steps]

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["changed"] == 0
    assert summary["summary"]["missing_left"] == 0
    assert summary["summary"]["missing_right"] == 0


def test_passive_listener_e2e_stream_capture_replay_assert(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-stream-state.json"
    capture_path = tmp_path / "listener-stream-capture.rpk"
    replay_path = tmp_path / "listener-stream-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        openai_stream = requests.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "stream hello"}],
                "stream": True,
            },
            timeout=2.0,
        )
        assert openai_stream.status_code == 200

        anthropic_stream = requests.post(
            f"{base_url}/v1/messages",
            json={
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": "stream hello"}],
                "stream": True,
            },
            timeout=2.0,
        )
        assert anthropic_stream.status_code == 200
    finally:
        _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    stream_requests = [
        step
        for step in run.steps
        if step.type == "model.request" and bool(step.input.get("payload", {}).get("stream"))
    ]
    assert len(stream_requests) >= 2

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    replay_run = read_artifact(replay_path)
    assert [step.type for step in run.steps] == [step.type for step in replay_run.steps]

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["changed"] == 0


def test_passive_listener_e2e_openai_responses_routes(tmp_path: Path) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-responses-state.json"
    capture_path = tmp_path / "listener-responses-capture.rpk"
    replay_path = tmp_path / "listener-responses-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

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

        v1_responses = requests.post(
            f"{base_url}/v1/responses",
            json={"model": "gpt-5.3-codex", "input": "say hello again"},
            timeout=2.0,
        )
        assert v1_responses.status_code == 200
        v1_payload = v1_responses.json()
        assert v1_payload["object"] == "response"
        assert v1_payload["status"] == "completed"
    finally:
        _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    assert [step.metadata.get("path") for step in run.steps] == [
        "/responses",
        "/responses",
        "/v1/responses",
        "/v1/responses",
    ]
    assert [step.metadata.get("provider") for step in run.steps] == [
        "openai",
        "openai",
        "openai",
        "openai",
    ]

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["identical"] == 4


def test_passive_listener_derives_tool_steps_from_openai_responses_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-tool-steps-state.json"
    capture_path = tmp_path / "listener-tool-steps-capture.rpk"

    with _fake_openai_upstream() as upstream_url:
        monkeypatch.setenv("REPLAYKIT_OPENAI_UPSTREAM_URL", upstream_url)
        host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
        base_url = f"http://{host}:{port}"
        try:
            response = requests.post(
                f"{base_url}/responses",
                json={
                    "model": "gpt-5.3-codex",
                    "input": [
                        {
                            "type": "function_call_output",
                            "name": "shell",
                            "call_id": "call-upstream-000001",
                            "output": {"stdout": "hello"},
                        }
                    ],
                },
                timeout=2.0,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["object"] == "response"
            assert payload["status"] == "completed"
        finally:
            _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "tool.response",
        "model.response",
        "tool.request",
    ]
    tool_response = run.steps[1]
    assert tool_response.input["tool"] == "shell"
    assert tool_response.input["call_id"] == "call-upstream-000001"
    assert tool_response.output["result"] == {"stdout": "hello"}
    assert tool_response.metadata["derived_from"] == "openai.responses.request_input"

    tool_request = run.steps[3]
    assert tool_request.input["tool"] == "shell"
    assert tool_request.input["call_id"] == "call-upstream-000001"
    assert tool_request.metadata["derived_from"] == "openai.responses.response_output"
    assert tool_request.metadata["event_type"] == "function_call"
    assert tool_request.output["status"] == "captured"


def test_passive_listener_e2e_codex_models_preflight_and_encoded_response(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    state_file = tmp_path / "listener-codex-state.json"
    capture_path = tmp_path / "listener-codex-capture.rpk"
    replay_path = tmp_path / "listener-codex-replay.rpk"

    host, port = _start_listener(runner, state_file=state_file, out_path=capture_path)
    base_url = f"http://{host}:{port}"

    try:
        models = requests.get(
            f"{base_url}/models",
            params={"client_version": "0.104.0"},
            timeout=2.0,
        )
        assert models.status_code == 200
        models_payload = models.json()
        assert models_payload["object"] == "list"
        model_ids = {item["id"] for item in models_payload["data"]}
        assert "gpt-5.3-codex" in model_ids

        encoded_payload = zstd.ZstdCompressor(write_content_size=False).compress(
            json.dumps(
                {"model": "gpt-5.3-codex", "input": "say hello"},
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        response = requests.post(
            f"{base_url}/responses",
            data=encoded_payload,
            headers={
                "content-type": "application/json",
                "content-encoding": "zstd",
                "accept": "text/event-stream",
            },
            timeout=2.0,
            stream=True,
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/event-stream")
        events = _read_sse_events(response)
        event_types = [event.get("type") for event in events]
        assert "response.created" in event_types
        assert "response.completed" in event_types
    finally:
        _stop_listener(runner, state_file=state_file)

    run = read_artifact(capture_path)
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "model.request",
        "model.response",
    ]
    assert [step.metadata.get("path") for step in run.steps] == [
        "/models",
        "/models",
        "/responses",
        "/responses",
    ]
    assert run.steps[2].input["payload"]["model"] == "gpt-5.3-codex"
    assert run.steps[2].input["payload"]["input"] == "say hello"

    replay = runner.invoke(
        app,
        [
            "replay",
            str(capture_path),
            "--out",
            str(replay_path),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ],
    )
    assert replay.exit_code == 0, replay.output

    assertion = runner.invoke(
        app,
        [
            "assert",
            str(replay_path),
            "--candidate",
            str(replay_path),
            "--json",
        ],
    )
    assert assertion.exit_code == 0, assertion.output
    summary = json.loads(assertion.stdout.strip())
    assert summary["status"] == "pass"
    assert summary["summary"]["identical"] == 4
