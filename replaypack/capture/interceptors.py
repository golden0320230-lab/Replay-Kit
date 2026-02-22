"""Capture wrappers for model, tool, and HTTP boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar

from replaypack.capture.context import CaptureContext, get_current_context
from replaypack.capture.exceptions import BoundaryPolicyError

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(slots=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None


@dataclass(slots=True)
class HttpResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None


def capture_model_call(
    model: str,
    input_payload: Any,
    invoke: Callable[[], T],
    *,
    context: CaptureContext | None = None,
    metadata: dict[str, Any] | None = None,
) -> T:
    ctx = context or get_current_context()
    if ctx is None:
        return invoke()

    run_metadata = {"boundary": "model", "model": model, **(metadata or {})}

    try:
        ctx.policy.assert_allowed("model", model)
    except BoundaryPolicyError as error:
        _record_policy_error(ctx, "model", model, error)
        raise

    ctx.record_step(
        "model.request",
        input_payload={"model": model, "input": input_payload},
        output_payload={"status": "sent"},
        metadata=run_metadata,
    )

    try:
        output = invoke()
    except Exception as error:
        _record_runtime_error(ctx, "model", model, error)
        raise

    ctx.record_step(
        "model.response",
        input_payload={"model": model},
        output_payload={"output": output},
        metadata=run_metadata,
    )
    return output


def capture_tool_call(
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    invoke: Callable[[], T],
    *,
    context: CaptureContext | None = None,
    metadata: dict[str, Any] | None = None,
) -> T:
    ctx = context or get_current_context()
    if ctx is None:
        return invoke()

    run_metadata = {"boundary": "tool", "tool": tool_name, **(metadata or {})}

    try:
        ctx.policy.assert_allowed("tool", tool_name)
    except BoundaryPolicyError as error:
        _record_policy_error(ctx, "tool", tool_name, error)
        raise

    ctx.record_step(
        "tool.request",
        input_payload={"tool": tool_name, "args": list(args), "kwargs": kwargs},
        output_payload={"status": "called"},
        metadata=run_metadata,
    )

    try:
        output = invoke()
    except Exception as error:
        _record_runtime_error(ctx, "tool", tool_name, error)
        raise

    ctx.record_step(
        "tool.response",
        input_payload={"tool": tool_name},
        output_payload={"result": output},
        metadata=run_metadata,
    )
    return output


def tool(name: str | None = None) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator for tool-boundary capture."""

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        tool_name = name or func.__name__

        @wraps(func)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            return capture_tool_call(
                tool_name=tool_name,
                args=tuple(args),
                kwargs=dict(kwargs),
                invoke=lambda: func(*args, **kwargs),
            )

        return wrapped

    return decorator


def capture_http_call(
    request: HttpRequest,
    send: Callable[[HttpRequest], HttpResponse],
    *,
    context: CaptureContext | None = None,
    metadata: dict[str, Any] | None = None,
) -> HttpResponse:
    ctx = context or get_current_context()
    if ctx is None:
        return send(request)

    run_metadata = {
        "boundary": "http",
        "method": request.method.upper(),
        "url": request.url,
        **(metadata or {}),
    }

    try:
        ctx.policy.assert_allowed("http", request.url)
    except BoundaryPolicyError as error:
        _record_policy_error(ctx, "http", request.url, error)
        raise

    req_body: Any
    if ctx.policy.capture_http_bodies:
        req_body = request.body
    else:
        req_body = "<omitted by policy>"

    ctx.record_step(
        "tool.request",
        input_payload={
            "method": request.method.upper(),
            "url": request.url,
            "headers": dict(request.headers),
            "body": req_body,
        },
        output_payload={"status": "sent"},
        metadata=run_metadata,
    )

    try:
        response = send(request)
    except Exception as error:
        _record_runtime_error(ctx, "http", request.url, error)
        raise

    response_body: Any
    if ctx.policy.capture_http_bodies:
        response_body = response.body
    else:
        response_body = "<omitted by policy>"

    ctx.record_step(
        "tool.response",
        input_payload={"method": request.method.upper(), "url": request.url},
        output_payload={
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body,
        },
        metadata=run_metadata,
    )

    return response


async def capture_http_call_async(
    request: HttpRequest,
    send: Callable[[HttpRequest], Awaitable[HttpResponse]],
    *,
    context: CaptureContext | None = None,
    metadata: dict[str, Any] | None = None,
) -> HttpResponse:
    """Async variant of HTTP boundary capture."""
    ctx = context or get_current_context()
    if ctx is None:
        return await send(request)

    run_metadata = {
        "boundary": "http",
        "method": request.method.upper(),
        "url": request.url,
        **(metadata or {}),
    }

    try:
        ctx.policy.assert_allowed("http", request.url)
    except BoundaryPolicyError as error:
        _record_policy_error(ctx, "http", request.url, error)
        raise

    req_body: Any
    if ctx.policy.capture_http_bodies:
        req_body = request.body
    else:
        req_body = "<omitted by policy>"

    ctx.record_step(
        "tool.request",
        input_payload={
            "method": request.method.upper(),
            "url": request.url,
            "headers": dict(request.headers),
            "body": req_body,
        },
        output_payload={"status": "sent"},
        metadata=run_metadata,
    )

    try:
        response = await send(request)
    except Exception as error:
        _record_runtime_error(ctx, "http", request.url, error)
        raise

    response_body: Any
    if ctx.policy.capture_http_bodies:
        response_body = response.body
    else:
        response_body = "<omitted by policy>"

    ctx.record_step(
        "tool.response",
        input_payload={"method": request.method.upper(), "url": request.url},
        output_payload={
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body,
        },
        metadata=run_metadata,
    )

    return response


def _record_policy_error(
    context: CaptureContext,
    boundary: str,
    target: str,
    error: BoundaryPolicyError,
) -> None:
    context.record_step(
        "error.event",
        input_payload={"boundary": boundary, "target": target},
        output_payload={
            "error_type": error.__class__.__name__,
            "message": str(error),
        },
        metadata={"boundary": boundary, "kind": "policy"},
    )


def _record_runtime_error(
    context: CaptureContext,
    boundary: str,
    target: str,
    error: Exception,
) -> None:
    context.record_step(
        "error.event",
        input_payload={"boundary": boundary, "target": target},
        output_payload={
            "error_type": error.__class__.__name__,
            "message": str(error),
        },
        metadata={"boundary": boundary, "kind": "runtime"},
    )
