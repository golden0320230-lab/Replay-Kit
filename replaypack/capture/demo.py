"""Demo capture workflow used by the M2 CLI command."""

from __future__ import annotations

from replaypack.capture.context import capture_run
from replaypack.capture.interceptors import (
    HttpRequest,
    HttpResponse,
    capture_http_call,
    capture_model_call,
    tool,
)
from replaypack.capture.policy import InterceptionPolicy
from replaypack.core.models import Run


@tool("demo.search")
def _demo_search_tool(query: str) -> dict[str, str]:
    return {"answer": f"result for {query}", "token": "sk-demo-tool-token"}


def build_demo_run(
    *,
    run_id: str = "run-demo-001",
    timestamp: str = "2026-02-21T00:00:00Z",
) -> Run:
    """Build a deterministic demo run spanning model/tool/http boundaries."""
    with capture_run(
        run_id=run_id,
        timestamp=timestamp,
        policy=InterceptionPolicy(capture_http_bodies=False),
    ) as context:
        capture_model_call(
            "gpt-4o-mini",
            {
                "messages": [{"role": "user", "content": "Summarize ReplayKit"}],
                "api_key": "sk-demo-model-key",
            },
            lambda: {"content": "ReplayKit records and replays runs.", "token": "sk-demo-model-token"},
        )

        _demo_search_tool("debugging")

        capture_http_call(
            HttpRequest(
                method="POST",
                url="https://api.example.com/v1/demo",
                headers={
                    "Authorization": "Bearer sk-demo-http-key",
                    "X-Trace-Id": "trace-demo-001",
                },
                body={"token": "sk-demo-body-token", "q": "debugging"},
            ),
            lambda _request: HttpResponse(
                status_code=200,
                headers={
                    "Content-Type": "application/json",
                    "Set-Cookie": "session=demo",
                },
                body={"ok": True, "email": "demo@example.com"},
            ),
        )

        return context.to_run()
