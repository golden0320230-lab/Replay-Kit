import json
from dataclasses import asdict
from pathlib import Path

from replaypack.listener_gateway import (
    normalize_provider_request,
    normalize_provider_response,
    provider_request_fingerprint,
)


def _fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "passive" / "provider_adapter_canonical.json"


def test_listener_provider_adapter_canonical_snapshot() -> None:
    openai_request = normalize_provider_request(
        provider="openai",
        path="/v1/chat/completions",
        payload={
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
            "model": "gpt-4o-mini",
            "metadata": {"z": 2, "a": 1},
        },
        headers={
            "X-Trace": "trace-001",
            "Authorization": "Bearer example-auth-header",
            "Host": "127.0.0.1",
        },
        request_id="openai-req-001",
    )
    openai_response = normalize_provider_response(
        provider="openai",
        status_code=200,
        payload={
            "object": "chat.completion",
            "id": "chatcmpl-upstream-001",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        },
    )
    openai_responses_request = normalize_provider_request(
        provider="openai",
        path="/responses",
        payload={
            "model": "gpt-5.3-codex",
            "input": "say hello",
            "metadata": {"session": "codex"},
        },
        headers={
            "X-Trace": "trace-responses-001",
            "Authorization": "Bearer example-auth-header",
        },
        request_id="openai-responses-req-001",
    )
    openai_responses_response = normalize_provider_response(
        provider="openai",
        status_code=200,
        payload={
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
                    "content": [{"type": "output_text", "text": "hello from responses"}],
                }
            ],
        },
    )

    anthropic_request = normalize_provider_request(
        provider="anthropic",
        path="/v1/messages",
        payload={
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers={
            "x-request-id": "anthropic-xreq-1",
            "authorization": "Bearer example-auth-header",
        },
        request_id="anthropic-req-001",
    )
    anthropic_response = normalize_provider_response(
        provider="anthropic",
        status_code=200,
        payload={
            "type": "message",
            "id": "msg-upstream-001",
            "content": [{"type": "text", "text": "hello"}],
        },
    )

    google_request = normalize_provider_request(
        provider="google",
        path="/v1beta/models/gemini-1.5-flash:generateContent",
        payload={
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        },
        headers={
            "X-Trace": "trace-google-001",
            "Content-Length": "999",
            "Connection": "keep-alive",
        },
        request_id="google-req-001",
    )
    google_response = normalize_provider_response(
        provider="google",
        status_code=503,
        payload={
            "error": {"message": "upstream unavailable"},
            "candidates": [],
        },
    )

    actual = {
        "openai": {
            "request": asdict(openai_request),
            "response": asdict(openai_response),
            "fingerprint": provider_request_fingerprint(openai_request),
        },
        "openai_responses": {
            "request": asdict(openai_responses_request),
            "response": asdict(openai_responses_response),
            "fingerprint": provider_request_fingerprint(openai_responses_request),
        },
        "anthropic": {
            "request": asdict(anthropic_request),
            "response": asdict(anthropic_response),
            "fingerprint": provider_request_fingerprint(anthropic_request),
        },
        "google": {
            "request": asdict(google_request),
            "response": asdict(google_response),
            "fingerprint": provider_request_fingerprint(google_request),
        },
    }

    expected = json.loads(_fixture_path().read_text(encoding="utf-8"))
    assert actual == expected


def test_listener_provider_adapter_fingerprint_stability() -> None:
    left = normalize_provider_request(
        provider="openai",
        path="/v1/chat/completions",
        payload={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
        headers={"X-Trace": "a", "Authorization": "Bearer token"},
        request_id="req-123",
    )
    right = normalize_provider_request(
        provider="openai",
        path="/v1/chat/completions",
        payload={"messages": [{"content": "hello", "role": "user"}], "model": "gpt-4o-mini"},
        headers={"Authorization": "Bearer token", "X-Trace": "a"},
        request_id="req-123",
    )

    assert provider_request_fingerprint(left) == provider_request_fingerprint(right)
