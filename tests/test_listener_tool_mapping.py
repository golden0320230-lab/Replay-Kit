from replaypack.listener_daemon import (
    _extract_openai_tool_requests_from_response,
    _extract_openai_tool_responses_from_request,
)


def test_extract_openai_tool_requests_from_response_supports_alias_fields() -> None:
    payload = {
        "output": [
            {
                "type": "tool_call",
                "tool": "shell",
                "id": "call-001",
                "input": {"command": "echo hi"},
            },
            {
                "type": "function_call",
                "name": "python_exec",
                "call_id": "call-002",
                "arguments": {"code": "print('ok')"},
            },
            {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
        ]
    }

    derived = _extract_openai_tool_requests_from_response(payload)
    assert len(derived) == 2

    first = derived[0]
    assert first["type"] == "tool_call"
    assert first["tool"] == "shell"
    assert first["call_id"] == "call-001"
    assert first["arguments"] == {"command": "echo hi"}

    second = derived[1]
    assert second["type"] == "function_call"
    assert second["tool"] == "python_exec"
    assert second["call_id"] == "call-002"
    assert second["arguments"] == {"code": "print('ok')"}


def test_extract_openai_tool_responses_from_request_supports_alias_fields() -> None:
    payload = {
        "input": [
            {
                "type": "tool_result",
                "tool_name": "shell",
                "id": "call-003",
                "result": {"stdout": "hello"},
            },
            {
                "type": "function_call_output",
                "name": "python_exec",
                "call_id": "call-004",
                "output": {"stdout": "ok"},
            },
            {"type": "message", "role": "user", "content": "ignored"},
        ]
    }

    derived = _extract_openai_tool_responses_from_request(payload)
    assert len(derived) == 2

    first = derived[0]
    assert first["type"] == "tool_result"
    assert first["tool"] == "shell"
    assert first["call_id"] == "call-003"
    assert first["result"] == {"stdout": "hello"}

    second = derived[1]
    assert second["type"] == "function_call_output"
    assert second["tool"] == "python_exec"
    assert second["call_id"] == "call-004"
    assert second["result"] == {"stdout": "ok"}
