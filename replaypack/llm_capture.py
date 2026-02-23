"""LLM capture helpers for provider-shaped CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from replaypack.capture import capture_run, intercept_openai_like
from replaypack.capture.redaction import (
    DEFAULT_REDACTION_POLICY,
    RedactionPolicy,
    redact_payload,
)
from replaypack.core.models import Run
from replaypack.providers import OpenAIProviderAdapter, FakeProviderAdapter, assemble_stream_capture


@dataclass(slots=True)
class _FakeProviderClient:
    """Deterministic fake provider used for adapter-wired llm capture."""

    def create(self, **kwargs: object) -> object:
        if kwargs.get("stream"):
            def iterator():
                yield {"choices": [{"delta": {"content": "Hel"}}]}
                yield {"choices": [{"delta": {"content": "lo"}}]}

            return iterator()

        return {
            "id": "fake-llm-001",
            "model": kwargs.get("model", "fake-chat"),
            "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
        }


def build_fake_llm_run(
    *,
    model: str,
    prompt: str,
    stream: bool,
    run_id: str,
    timestamp: str = "2026-02-22T00:00:00Z",
    redaction_policy: RedactionPolicy | None = None,
) -> Run:
    """Build fake-provider run using openai-like interception + provider adapter."""
    adapter = FakeProviderAdapter()
    client = _FakeProviderClient()
    payload = {"messages": [{"role": "user", "content": prompt}]}
    request_view = adapter.capture_request(model=model, payload=payload, stream=stream)
    effective_policy = redaction_policy or DEFAULT_REDACTION_POLICY

    response: object
    chunks: list[Any] = []

    with capture_run(
        run_id=run_id,
        timestamp=timestamp,
        redaction_policy=redaction_policy,
    ) as context:
        with intercept_openai_like(
            _FakeProviderClient,
            provider="fake",
            adapter_name="fake.provider-adapter",
            context=context,
        ):
            if stream:
                chunks = list(
                    client.create(
                        model=model,
                        messages=payload["messages"],
                        stream=True,
                    )
                )
                response = assemble_stream_capture(adapter, chunks=chunks)
            else:
                non_stream = client.create(
                    model=model,
                    messages=payload["messages"],
                    stream=False,
                )
                response = adapter.capture_response(response=non_stream)

        run = context.to_run()

    if run.steps:
        first = run.steps[0]
        first.input = {
            "model": model,
            "input": redact_payload(request_view, policy=effective_policy),
        }
        first.metadata["provider_adapter"] = adapter.name
        first.metadata["adapter_name"] = "fake.provider-adapter"

    if len(run.steps) >= 2:
        second = run.steps[1]
        second.output = {"output": redact_payload(response, policy=effective_policy)}
        second.metadata["provider_adapter"] = adapter.name
        second.metadata["adapter_name"] = "fake.provider-adapter"

    run.source = "llm.capture"
    run.provider = adapter.name
    return run


def build_openai_llm_run(
    *,
    model: str,
    prompt: str,
    stream: bool,
    run_id: str,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
    timestamp: str = "2026-02-22T00:00:00Z",
    redaction_policy: RedactionPolicy | None = None,
    request_post: Callable[..., Any] | None = None,
) -> Run:
    """Build OpenAI provider run with adapter-normalized request/response steps."""
    import requests

    adapter = OpenAIProviderAdapter()
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
    }
    post_fn = request_post or requests.post
    effective_policy = redaction_policy or DEFAULT_REDACTION_POLICY

    with capture_run(
        run_id=run_id,
        timestamp=timestamp,
        redaction_policy=effective_policy,
    ) as context:
        request_view = adapter.normalize_request(
            model=model,
            payload=payload,
            headers=headers,
            url=endpoint,
            stream=stream,
        )
        context.record_step(
            "model.request",
            input_payload={"model": model, "input": request_view},
            output_payload={"status": "sent"},
            metadata={
                "provider": adapter.name,
                "model": model,
                "stream": stream,
                "endpoint": endpoint,
                "adapter_name": "openai.provider-adapter",
            },
        )

        response = post_fn(
            endpoint,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
            stream=stream,
        )
        response.raise_for_status()

        if stream:
            raw_chunks = list(_iter_openai_stream_chunks(response))
            normalized_response = assemble_stream_capture(adapter, chunks=raw_chunks)
        else:
            normalized_response = adapter.normalize_response(response=response.json())

        context.record_step(
            "model.response",
            input_payload={"request_url": endpoint},
            output_payload={"output": adapter.redact(normalized_response, policy=effective_policy)},
            metadata={
                "provider": adapter.name,
                "model": model,
                "stream": stream,
                "endpoint": endpoint,
                "status_code": getattr(response, "status_code", 200),
                "adapter_name": "openai.provider-adapter",
            },
        )
        run = context.to_run()

    run.source = "llm.capture"
    run.provider = adapter.name
    return run


def _iter_openai_stream_chunks(response: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for raw_line in response.iter_lines():
        if raw_line is None:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        stripped = line.strip()
        if not stripped or not stripped.startswith("data:"):
            continue
        payload = stripped[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict):
            chunks.append(chunk)
    return chunks
