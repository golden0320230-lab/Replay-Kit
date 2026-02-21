import pytest

from replaypack.capture import (
    BoundaryPolicyError,
    HttpRequest,
    HttpResponse,
    InterceptionPolicy,
    capture_http_call,
    capture_model_call,
    capture_run,
    tool,
)


def test_capture_records_model_tool_and_http_boundaries() -> None:
    @tool("search")
    def search_tool(query: str, api_key: str) -> dict[str, str]:
        return {"answer": f"result for {query}", "token": "sk-supersecrettoken"}

    with capture_run(
        run_id="run-capture-001",
        timestamp="2026-02-21T15:00:00Z",
        policy=InterceptionPolicy(capture_http_bodies=False),
    ) as context:
        model_output = capture_model_call(
            "gpt-4o-mini",
            {
                "messages": [{"role": "user", "content": "hello"}],
                "api_key": "sk-secret-model-key",
            },
            lambda: {"content": "hi", "token": "sk-secret-response-token"},
        )

        tool_output = search_tool("weather", api_key="sk-secret-tool-key")

        request = HttpRequest(
            method="POST",
            url="https://api.example.com/v1/search",
            headers={
                "Authorization": "Bearer sk-secret-auth-token",
                "X-Trace-Id": "trace-001",
            },
            body={"query": "weather", "token": "sk-secret-body-token"},
        )

        response = capture_http_call(
            request,
            lambda _req: HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json", "Set-Cookie": "session=abc"},
                body={"ok": True, "email": "user@example.com"},
            ),
        )

        run = context.to_run()

    assert model_output["content"] == "hi"
    assert "answer" in tool_output
    assert response.status_code == 200

    assert [step.id for step in run.steps] == [
        "step-000001",
        "step-000002",
        "step-000003",
        "step-000004",
        "step-000005",
        "step-000006",
    ]
    assert [step.type for step in run.steps] == [
        "model.request",
        "model.response",
        "tool.request",
        "tool.response",
        "tool.request",
        "tool.response",
    ]

    model_request = run.steps[0]
    tool_request = run.steps[2]
    http_request = run.steps[4]
    http_response = run.steps[5]

    assert model_request.input["input"]["api_key"] == "[REDACTED]"
    assert model_request.hash.startswith("sha256:")

    assert tool_request.input["kwargs"]["api_key"] == "[REDACTED]"

    assert http_request.input["headers"]["Authorization"] == "[REDACTED]"
    assert http_request.input["body"] == "<omitted by policy>"
    assert http_response.output["headers"]["Set-Cookie"] == "[REDACTED]"
    assert http_response.output["body"] == "<omitted by policy>"


def test_http_policy_deny_records_error_event_with_diagnostics() -> None:
    policy = InterceptionPolicy(blocked_hosts=frozenset({"blocked.example.com"}))

    with capture_run(
        run_id="run-capture-deny-001",
        timestamp="2026-02-21T15:05:00Z",
        policy=policy,
    ) as context:
        request = HttpRequest(
            method="GET",
            url="https://blocked.example.com/api",
            headers={},
            body=None,
        )

        with pytest.raises(BoundaryPolicyError, match="blocked host"):
            capture_http_call(request, lambda _req: HttpResponse(status_code=200))

        run = context.to_run()

    assert len(run.steps) == 1
    assert run.steps[0].type == "error.event"
    assert "blocked host" in run.steps[0].output["message"]


def test_tool_runtime_errors_are_recorded_as_error_event() -> None:
    @tool("explode")
    def explode_tool() -> None:
        raise RuntimeError("boom")

    with capture_run(
        run_id="run-capture-error-001",
        timestamp="2026-02-21T15:10:00Z",
    ) as context:
        with pytest.raises(RuntimeError, match="boom"):
            explode_tool()

        run = context.to_run()

    assert [step.type for step in run.steps] == ["tool.request", "error.event"]
    assert run.steps[-1].output["error_type"] == "RuntimeError"


def test_wrappers_are_passthrough_without_active_context() -> None:
    @tool("adder")
    def adder(a: int, b: int) -> int:
        return a + b

    out = capture_model_call(
        "gpt-4o-mini",
        {"prompt": "hello"},
        lambda: {"content": "world"},
        context=None,
    )

    assert out["content"] == "world"
    assert adder(2, 3) == 5
