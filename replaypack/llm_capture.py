"""LLM capture helpers for provider-shaped CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from replaypack.capture import capture_run, intercept_openai_like
from replaypack.core.models import Run
from replaypack.providers import FakeProviderAdapter, assemble_stream_capture


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
) -> Run:
    """Build fake-provider run using openai-like interception + provider adapter."""
    adapter = FakeProviderAdapter()
    client = _FakeProviderClient()
    payload = {"messages": [{"role": "user", "content": prompt}]}
    request_view = adapter.capture_request(model=model, payload=payload, stream=stream)

    response: object
    chunks: list[Any] = []

    with capture_run(run_id=run_id, timestamp=timestamp) as context:
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
        first.input = {"model": model, "input": request_view}
        first.metadata["provider_adapter"] = adapter.name
        first.metadata["adapter_name"] = "fake.provider-adapter"

    if len(run.steps) >= 2:
        second = run.steps[1]
        second.output = {"output": response}
        second.metadata["provider_adapter"] = adapter.name
        second.metadata["adapter_name"] = "fake.provider-adapter"

    return run
