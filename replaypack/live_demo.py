"""Local fake-provider live demo capture helpers."""

from __future__ import annotations

from dataclasses import dataclass

from replaypack.capture import capture_run, intercept_openai_like
from replaypack.core.models import Run


@dataclass(slots=True)
class _FakeProviderClient:
    """Deterministic fake provider used for local live-demo capture."""

    def create(self, **kwargs: object) -> object:
        if kwargs.get("stream"):
            def iterator():
                yield {"choices": [{"delta": {"content": "Hel"}}]}
                yield {"choices": [{"delta": {"content": "lo"}}]}

            return iterator()

        return {
            "id": "fake-live-demo-001",
            "model": kwargs.get("model", "fake-chat"),
            "content": "Hello",
        }


def build_live_demo_run(
    *,
    provider: str = "fake",
    stream: bool = False,
    model: str = "fake-chat",
    prompt: str = "say hello",
    run_id: str = "run-live-demo-001",
    timestamp: str = "2026-02-22T00:00:00Z",
) -> Run:
    """Build a deterministic model-shaped run without external network access."""
    normalized_provider = provider.strip().lower()
    if normalized_provider != "fake":
        raise ValueError(
            f"Unsupported live-demo provider: {provider}. Expected fake."
        )

    client = _FakeProviderClient()
    with capture_run(run_id=run_id, timestamp=timestamp) as context:
        with intercept_openai_like(
            _FakeProviderClient,
            provider="fake",
            adapter_name="fake.live-demo",
            context=context,
        ):
            if stream:
                list(
                    client.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        stream=True,
                    )
                )
            else:
                client.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=False,
                )

        return context.to_run()
