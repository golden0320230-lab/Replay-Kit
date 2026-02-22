"""Scoped drop-in interception adapters for HTTP and LLM clients."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from importlib import import_module
import inspect
from typing import Any

from replaypack.capture.context import CaptureContext, get_current_context
from replaypack.capture.exceptions import BoundaryPolicyError
from replaypack.capture.interceptors import (
    HttpRequest,
    HttpResponse,
    capture_http_call,
    capture_http_call_async,
)


@contextmanager
def intercept_requests(
    *,
    context: CaptureContext | None = None,
) -> Iterator[None]:
    """Patch requests Session.request within scope and capture HTTP boundaries."""
    requests_module = import_module("requests")
    session_cls = requests_module.sessions.Session
    original_request = session_cls.request

    def wrapped_request(self: Any, method: str, url: str, **kwargs: Any) -> Any:
        request = HttpRequest(
            method=method,
            url=str(url),
            headers=dict(kwargs.get("headers") or {}),
            body=_extract_request_body(kwargs),
        )
        response_holder: dict[str, Any] = {}

        def send(_request: HttpRequest) -> HttpResponse:
            response = original_request(self, method, url, **kwargs)
            response_holder["response"] = response
            return HttpResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=_extract_response_body(response, streamed=bool(kwargs.get("stream"))),
            )

        capture_http_call(
            request,
            send,
            context=context,
            metadata={"adapter": "requests", "client": "sync"},
        )
        return response_holder["response"]

    session_cls.request = wrapped_request
    try:
        yield
    finally:
        session_cls.request = original_request


@contextmanager
def intercept_httpx(
    *,
    context: CaptureContext | None = None,
) -> Iterator[None]:
    """Patch httpx Client/AsyncClient request methods within scope."""
    httpx_module = import_module("httpx")
    client_cls = httpx_module.Client
    async_client_cls = httpx_module.AsyncClient

    original_client_request = client_cls.request
    original_async_client_request = async_client_cls.request

    def wrapped_client_request(self: Any, method: str, url: Any, **kwargs: Any) -> Any:
        request = HttpRequest(
            method=method,
            url=str(url),
            headers=dict(kwargs.get("headers") or {}),
            body=_extract_request_body(kwargs),
        )
        response_holder: dict[str, Any] = {}

        def send(_request: HttpRequest) -> HttpResponse:
            response = original_client_request(self, method, url, **kwargs)
            response_holder["response"] = response
            return HttpResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=_extract_response_body(response, streamed=bool(kwargs.get("stream"))),
            )

        capture_http_call(
            request,
            send,
            context=context,
            metadata={"adapter": "httpx", "client": "sync"},
        )
        return response_holder["response"]

    async def wrapped_async_client_request(
        self: Any,
        method: str,
        url: Any,
        **kwargs: Any,
    ) -> Any:
        request = HttpRequest(
            method=method,
            url=str(url),
            headers=dict(kwargs.get("headers") or {}),
            body=_extract_request_body(kwargs),
        )
        response_holder: dict[str, Any] = {}

        async def send(_request: HttpRequest) -> HttpResponse:
            response = await original_async_client_request(self, method, url, **kwargs)
            response_holder["response"] = response
            return HttpResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=_extract_response_body(response, streamed=bool(kwargs.get("stream"))),
            )

        await capture_http_call_async(
            request,
            send,
            context=context,
            metadata={"adapter": "httpx", "client": "async"},
        )
        return response_holder["response"]

    client_cls.request = wrapped_client_request
    async_client_cls.request = wrapped_async_client_request
    try:
        yield
    finally:
        client_cls.request = original_client_request
        async_client_cls.request = original_async_client_request


@contextmanager
def intercept_openai_like(
    target: Any,
    *,
    method_name: str = "create",
    provider: str = "openai",
    adapter_name: str = "openai.like",
    context: CaptureContext | None = None,
) -> Iterator[None]:
    """Patch an OpenAI-like client method and capture model boundaries.

    The target method is expected to return either:
    - a non-streaming response object, or
    - an iterator of stream chunks when called with ``stream=True``.
    """

    original_method = getattr(target, method_name)
    if inspect.iscoroutinefunction(original_method):
        raise TypeError(
            "intercept_openai_like currently supports synchronous methods only."
        )

    def wrapped_method(*args: Any, **kwargs: Any) -> Any:
        capture_args = _strip_bound_self(args, target)
        stream = bool(kwargs.get("stream"))
        model = _extract_model(capture_args, kwargs)
        input_payload = _build_model_input_payload(capture_args, kwargs)
        metadata = {
            "boundary": "model",
            "provider": provider,
            "adapter": adapter_name,
            "stream": stream,
        }

        if not stream:
            from replaypack.capture.interceptors import capture_model_call

            return capture_model_call(
                model,
                input_payload,
                lambda: original_method(*args, **kwargs),
                context=context,
                metadata=metadata,
            )

        ctx = context or get_current_context()
        if ctx is None:
            return original_method(*args, **kwargs)

        try:
            ctx.policy.assert_allowed("model", model)
        except BoundaryPolicyError as error:
            _record_model_error(ctx, model, error, kind="policy")
            raise

        ctx.record_step(
            "model.request",
            input_payload={"model": model, "input": input_payload},
            output_payload={"status": "sent"},
            metadata=metadata,
        )

        try:
            stream_result = original_method(*args, **kwargs)
        except Exception as error:
            _record_model_error(ctx, model, error, kind="runtime")
            raise

        return _CapturedSyncStream(
            source=stream_result,
            context=ctx,
            model=model,
            metadata=metadata,
        )

    setattr(target, method_name, wrapped_method)
    try:
        yield
    finally:
        setattr(target, method_name, original_method)


class _CapturedSyncStream:
    def __init__(
        self,
        *,
        source: Any,
        context: CaptureContext,
        model: str,
        metadata: dict[str, Any],
    ) -> None:
        self._iterator = iter(source)
        self._context = context
        self._model = model
        self._metadata = metadata
        self._chunks: list[Any] = []
        self._assembled_parts: list[str] = []
        self._completed = False

    def __iter__(self) -> "_CapturedSyncStream":
        return self

    def __next__(self) -> Any:
        try:
            chunk = next(self._iterator)
        except StopIteration:
            self._record_complete()
            raise
        except Exception as error:
            if not self._completed:
                _record_model_error(self._context, self._model, error, kind="runtime")
                self._completed = True
            raise

        self._chunks.append(_to_capture_value(chunk))
        text_part = _extract_chunk_text(chunk)
        if text_part:
            self._assembled_parts.append(text_part)
        return chunk

    def _record_complete(self) -> None:
        if self._completed:
            return
        self._context.record_step(
            "model.response",
            input_payload={"model": self._model},
            output_payload={
                "output": {
                    "stream": True,
                    "chunks": self._chunks,
                    "assembled_text": "".join(self._assembled_parts),
                }
            },
            metadata=self._metadata,
        )
        self._completed = True


def _extract_request_body(kwargs: dict[str, Any]) -> Any:
    if "json" in kwargs:
        return kwargs.get("json")
    if "data" in kwargs:
        return kwargs.get("data")
    if "content" in kwargs:
        return kwargs.get("content")
    return None


def _extract_response_body(response: Any, *, streamed: bool) -> Any:
    if streamed:
        return "<streaming response omitted>"
    if hasattr(response, "text"):
        try:
            return response.text
        except Exception:  # pragma: no cover - defensive fallback
            pass
    if hasattr(response, "content"):
        content = getattr(response, "content")
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return content
    return None


def _extract_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    model = kwargs.get("model")
    if isinstance(model, str) and model:
        return model
    if args and isinstance(args[0], str):
        return args[0]
    return "unknown-model"


def _strip_bound_self(args: tuple[Any, ...], target: Any) -> tuple[Any, ...]:
    if not args:
        return args
    first = args[0]
    if inspect.isclass(target) and isinstance(first, target):
        return args[1:]
    if first is target:
        return args[1:]
    return args


def _build_model_input_payload(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"kwargs": _to_capture_value(kwargs)}
    if args:
        payload["args"] = [_to_capture_value(arg) for arg in args]
    return payload


def _extract_chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk

    if isinstance(chunk, dict):
        choices = chunk.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        return content

    choices_attr = getattr(chunk, "choices", None)
    if isinstance(choices_attr, list) and choices_attr:
        first_choice = choices_attr[0]
        delta_attr = getattr(first_choice, "delta", None)
        content_attr = getattr(delta_attr, "content", None)
        if isinstance(content_attr, str):
            return content_attr

    return ""


def _to_capture_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_capture_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_capture_value(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _to_capture_value(value.model_dump())
        except Exception:  # pragma: no cover - defensive fallback
            pass
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return _to_capture_value(value.dict())
        except Exception:  # pragma: no cover - defensive fallback
            pass
    return repr(value)


def _record_model_error(
    context: CaptureContext,
    model: str,
    error: Exception,
    *,
    kind: str,
) -> None:
    context.record_step(
        "error.event",
        input_payload={"boundary": "model", "target": model},
        output_payload={
            "error_type": error.__class__.__name__,
            "message": str(error),
        },
        metadata={"boundary": "model", "kind": kind},
    )
