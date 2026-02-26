"""Passive listener daemon process for ReplayKit lifecycle commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import io
import json
import os
from pathlib import Path
import signal
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlsplit
import zlib

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover - dependency is required in production/test envs
    zstd = None

from replaypack.artifact import write_artifact
from replaypack.core.models import Run, Step
from replaypack.listener_gateway import (
    ProviderResponse,
    build_best_effort_fallback_response,
    build_openai_models_payload,
    build_provider_response,
    detect_provider,
    normalize_provider_request,
    normalize_provider_response,
    provider_request_fingerprint,
)
from replaypack.listener_agent_gateway import detect_agent, normalize_agent_events
from replaypack.listener_redaction import redact_listener_headers, redact_listener_value
from replaypack.listener_state import remove_listener_state, write_listener_state

_PERSIST_DELAY_ENV = "REPLAYKIT_LISTENER_PERSIST_DELAY_SECONDS"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_UPSTREAM_ENV_BY_PROVIDER = {
    "openai": "REPLAYKIT_OPENAI_UPSTREAM_URL",
    "anthropic": "REPLAYKIT_ANTHROPIC_UPSTREAM_URL",
    "google": "REPLAYKIT_GEMINI_UPSTREAM_URL",
}
_UPSTREAM_ENV_FALLBACK = "REPLAYKIT_PROVIDER_UPSTREAM_URL"
_UPSTREAM_TIMEOUT_ENV = "REPLAYKIT_LISTENER_UPSTREAM_TIMEOUT_SECONDS"
_UPSTREAM_DEFAULT_TIMEOUT_SECONDS = 5.0
_PAYLOAD_STRING_LIMIT_ENV = "REPLAYKIT_LISTENER_PAYLOAD_STRING_LIMIT"
_PAYLOAD_STRING_DEFAULT_LIMIT = 4096
_OPENAI_RESPONSES_PATHS = {"/responses", "/v1/responses"}
_OPENAI_TOOL_REQUEST_TYPES = {
    "function_call",
    "tool_call",
    "computer_call",
    "code_interpreter_call",
    "mcp_call",
}
_OPENAI_TOOL_RESPONSE_TYPES = {
    "function_call_output",
    "tool_result",
    "tool_response",
    "computer_call_output",
    "code_interpreter_call_output",
    "mcp_result",
}


def _resolve_provider_upstream_base_url(provider: str) -> str | None:
    env_keys = [_UPSTREAM_ENV_BY_PROVIDER.get(provider), _UPSTREAM_ENV_FALLBACK]
    for env_key in env_keys:
        if not env_key:
            continue
        value = os.environ.get(env_key, "").strip()
        if value:
            return value.rstrip("/")
    return None


def _resolve_upstream_timeout_seconds() -> float:
    raw = os.environ.get(_UPSTREAM_TIMEOUT_ENV)
    if raw is None:
        return _UPSTREAM_DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _UPSTREAM_DEFAULT_TIMEOUT_SECONDS
    if parsed <= 0:
        return _UPSTREAM_DEFAULT_TIMEOUT_SECONDS
    return min(parsed, 120.0)


def _resolve_payload_string_limit() -> int:
    raw = os.environ.get(_PAYLOAD_STRING_LIMIT_ENV)
    if raw is None:
        return _PAYLOAD_STRING_DEFAULT_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return _PAYLOAD_STRING_DEFAULT_LIMIT
    return max(0, parsed)


def _truncate_payload_strings(value: Any, *, limit: int) -> tuple[Any, int]:
    if limit <= 0:
        return value, 0
    truncated_count = 0

    def _walk(current: Any) -> Any:
        nonlocal truncated_count
        if isinstance(current, dict):
            return {
                str(key): _walk(val)
                for key, val in sorted(current.items(), key=lambda item: str(item[0]))
            }
        if isinstance(current, list):
            return [_walk(item) for item in current]
        if isinstance(current, tuple):
            return [_walk(item) for item in current]
        if isinstance(current, str) and len(current) > limit:
            truncated_count += 1
            overflow = len(current) - limit
            return f"{current[:limit]}...[TRUNCATED {overflow} chars]"
        return current

    return _walk(value), truncated_count


def _extract_openai_tool_requests_from_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output_items = payload.get("output")
    if not isinstance(output_items, list):
        return []
    derived: list[dict[str, Any]] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type not in _OPENAI_TOOL_REQUEST_TYPES:
            continue
        tool_name = str(
            item.get("name")
            or item.get("tool")
            or item.get("tool_name")
            or item.get("recipient_name")
            or item_type
        )
        call_id = item.get("call_id") or item.get("id")
        arguments = item.get("arguments")
        if arguments is None and "input" in item:
            arguments = item.get("input")
        derived.append(
            {
                "type": item_type,
                "tool": tool_name,
                "call_id": str(call_id) if call_id is not None else None,
                "arguments": arguments,
                "event": item,
            }
        )
    return derived


def _extract_openai_tool_responses_from_request(payload: dict[str, Any]) -> list[dict[str, Any]]:
    request_input = payload.get("input")
    if isinstance(request_input, list):
        input_items = request_input
    elif isinstance(request_input, dict):
        input_items = [request_input]
    else:
        return []
    derived: list[dict[str, Any]] = []
    for item in input_items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type not in _OPENAI_TOOL_RESPONSE_TYPES:
            continue
        tool_name = str(
            item.get("name")
            or item.get("tool")
            or item.get("tool_name")
            or item_type
        )
        call_id = item.get("call_id") or item.get("id")
        result_payload = item.get("output")
        if result_payload is None and "result" in item:
            result_payload = item.get("result")
        if result_payload is None and "content" in item:
            result_payload = item.get("content")
        if result_payload is None:
            result_payload = item
        derived.append(
            {
                "type": item_type,
                "tool": tool_name,
                "call_id": str(call_id) if call_id is not None else None,
                "result": result_payload,
                "event": item,
            }
        )
    return derived


def _forward_provider_request(
    *,
    upstream_base_url: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str | None]:
    target_url = f"{upstream_base_url}{path}"
    forward_headers = {
        key: value
        for key, value in headers.items()
        if key
        and key.lower()
        not in {"host", "content-length", "connection"}
        and not key.lower().startswith("x-replaykit-")
    }
    if "content-type" not in {key.lower() for key in forward_headers}:
        forward_headers["content-type"] = "application/json"

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        target_url,
        data=body,
        headers=forward_headers,
        method="POST",
    )
    opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            raw_body = response.read().decode("utf-8")
    except urllib_error.HTTPError as error:
        status_code = int(error.code)
        raw_body = error.read().decode("utf-8")
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as error:
        return 0, {}, str(error)

    if not raw_body:
        parsed_body: dict[str, Any] = {}
    else:
        try:
            parsed_payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return 0, {}, "upstream returned non-JSON response body"
        if not isinstance(parsed_payload, dict):
            return 0, {}, "upstream returned non-object JSON response body"
        parsed_body = parsed_payload
    return status_code, parsed_body, None


class _ListenerRunRecorder:
    def __init__(
        self,
        *,
        session_id: str,
        out_path: Path,
        host: str,
        port: int,
        allow_synthetic: bool,
        payload_string_limit: int,
    ) -> None:
        self._lock = threading.Lock()
        self._out_path = out_path
        self._allow_synthetic = allow_synthetic
        self._payload_string_limit = max(0, int(payload_string_limit))
        self._step_sequence = 0
        self._request_sequence = 0
        self._agent_event_sequence = 0
        timestamp = _utc_now()
        self._run = Run(
            id=f"run-listener-{session_id}",
            timestamp=timestamp,
            source="listener",
            capture_mode="passive",
            listener_session_id=session_id,
            listener_process={
                "pid": os.getpid(),
                "executable": sys.executable,
                "command": list(sys.argv),
                "cwd": str(Path.cwd()),
            },
            listener_bind={"host": host, "port": port},
            environment_fingerprint={"listener_mode": "passive", "os": os.name},
            runtime_versions={
                "python": ".".join(
                    str(part) for part in sys.version_info[:3]
                ),
                "replaykit_listener": "1",
            },
            steps=[],
        )
        self._persist_locked()

    @property
    def out_path(self) -> Path:
        return self._out_path

    def record_provider_transaction(
        self,
        *,
        provider: str,
        path: str,
        query_params: dict[str, Any] | None,
        payload: dict[str, Any],
        headers: dict[str, str],
        fail_reason: str | None,
    ) -> tuple[int, dict[str, Any]]:
        with self._lock:
            self._request_sequence += 1
            request_id = (
                str(headers.get("x-request-id")).strip()
                if headers.get("x-request-id")
                else f"{provider}-request-{self._request_sequence:06d}"
            )
            request = normalize_provider_request(
                provider=provider,
                path=path,
                payload=payload,
                headers=headers,
                request_id=request_id,
            )
            minimized_payload, truncated_fields = _truncate_payload_strings(
                request.payload,
                limit=self._payload_string_limit,
            )
            correlation_id = provider_request_fingerprint(request)

            response_source = "synthetic"
            synthetic_block_reason: str | None = None
            if fail_reason:
                if self._allow_synthetic:
                    status_code, response_payload, normalized_response = build_provider_response(
                        request=request,
                        sequence=self._request_sequence,
                        fail_reason=fail_reason,
                    )
                else:
                    response_source = "synthetic_blocked"
                    synthetic_block_reason = str(fail_reason)
                    status_code, response_payload, normalized_response = build_provider_response(
                        request=request,
                        sequence=self._request_sequence,
                        fail_reason=(
                            "synthetic_fallback_blocked_by_policy: "
                            f"{synthetic_block_reason}"
                        ),
                    )
            else:
                upstream_base_url = _resolve_provider_upstream_base_url(provider)
                supports_upstream_forward = path not in {"/models", "/v1/models"}
                if upstream_base_url and supports_upstream_forward:
                    response_source = "upstream"
                    (
                        status_code,
                        response_payload,
                        upstream_error,
                    ) = _forward_provider_request(
                        upstream_base_url=upstream_base_url,
                        path=path,
                        payload=request.payload,
                        headers=request.headers,
                        timeout_seconds=_resolve_upstream_timeout_seconds(),
                    )
                    if upstream_error:
                        if self._allow_synthetic:
                            response_source = "upstream_error"
                            status_code, response_payload, normalized_response = (
                                build_provider_response(
                                    request=request,
                                    sequence=self._request_sequence,
                                    fail_reason=f"upstream_forward_failed: {upstream_error}",
                                )
                            )
                        else:
                            response_source = "synthetic_blocked"
                            synthetic_block_reason = (
                                "upstream_forward_failed: "
                                f"{upstream_error}"
                            )
                            status_code, response_payload, normalized_response = (
                                build_provider_response(
                                    request=request,
                                    sequence=self._request_sequence,
                                    fail_reason=(
                                        "synthetic_fallback_blocked_by_policy: "
                                        f"{synthetic_block_reason}"
                                    ),
                                )
                            )
                    else:
                        normalized_response = normalize_provider_response(
                            provider=provider,
                            status_code=status_code,
                            payload=response_payload,
                        )
                else:
                    if self._allow_synthetic or not supports_upstream_forward:
                        status_code, response_payload, normalized_response = build_provider_response(
                            request=request,
                            sequence=self._request_sequence,
                            fail_reason=None,
                        )
                    else:
                        response_source = "synthetic_blocked"
                        synthetic_block_reason = "no_upstream_configured"
                        status_code, response_payload, normalized_response = build_provider_response(
                            request=request,
                            sequence=self._request_sequence,
                            fail_reason=(
                                "synthetic_fallback_blocked_by_policy: "
                                f"{synthetic_block_reason}"
                            ),
                        )

            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="model.request",
                    input={
                        "provider": provider,
                        "path": path,
                        "query": redact_listener_value(query_params or {}),
                        "request_id": request.request_id,
                        "model": request.model,
                        "stream": request.stream,
                        "headers": redact_listener_headers(request.headers),
                        "payload": redact_listener_value(minimized_payload),
                    },
                    output={"status": "captured"},
                    metadata=redact_listener_value(
                        {
                            "provider": provider,
                            "path": path,
                            "request_id": request.request_id,
                            "correlation_id": correlation_id,
                            "capture_mode": "passive",
                            "response_source": response_source,
                            "payload_truncated_fields": truncated_fields,
                            "payload_string_limit": self._payload_string_limit,
                        }
                    ),
                    timestamp=_utc_now(),
                )
            )
            if provider == "openai" and path in _OPENAI_RESPONSES_PATHS:
                for tool_response in _extract_openai_tool_responses_from_request(request.payload):
                    self._run.steps.append(
                        Step(
                            id=self._next_step_id(),
                            type="tool.response",
                            input=redact_listener_value(
                                {
                                    "tool": tool_response["tool"],
                                    "call_id": tool_response["call_id"],
                                    "request_id": request.request_id,
                                }
                            ),
                            output=redact_listener_value(
                                {
                                    "result": tool_response["result"],
                                    "event": tool_response["event"],
                                }
                            ),
                            metadata=redact_listener_value(
                                {
                                    "provider": provider,
                                    "path": path,
                                    "request_id": request.request_id,
                                    "correlation_id": correlation_id,
                                    "capture_mode": "passive",
                                    "response_source": response_source,
                                    "derived_from": "openai.responses.request_input",
                                    "event_type": tool_response["type"],
                                }
                            ),
                            timestamp=_utc_now(),
                        )
                    )
            if synthetic_block_reason is not None:
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type="error.event",
                        input=redact_listener_value(
                            {
                                "source": "listener",
                                "category": "synthetic_blocked",
                                "request_id": request.request_id,
                            }
                        ),
                        output=redact_listener_value(
                            {
                                "message": "synthetic fallback blocked by listener policy",
                                "details": {
                                    "provider": provider,
                                    "path": path,
                                    "request_id": request.request_id,
                                    "reason": synthetic_block_reason,
                                },
                            }
                        ),
                        metadata=redact_listener_value(
                            {
                                "source": "listener",
                                "category": "synthetic_blocked",
                                "provider": provider,
                                "path": path,
                                "request_id": request.request_id,
                                "correlation_id": correlation_id,
                                "capture_mode": "passive",
                            }
                        ),
                        timestamp=_utc_now(),
                    )
                )
            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="model.response",
                    input=redact_listener_value({"request_id": request.request_id}),
                    output={
                        "status_code": status_code,
                        "output": redact_listener_value(normalized_response.response),
                        "assembled_text": redact_listener_value(
                            normalized_response.assembled_text
                        ),
                        "stream": self._stream_payload(
                            request_id=request.request_id,
                            correlation_id=correlation_id,
                            normalized_response=normalized_response,
                            status_code=status_code,
                        ),
                        "error": redact_listener_value(normalized_response.error),
                    },
                    metadata=redact_listener_value(
                        {
                            "provider": provider,
                            "path": path,
                            "request_id": request.request_id,
                            "correlation_id": correlation_id,
                            "capture_mode": "passive",
                            "response_source": response_source,
                        }
                    ),
                    timestamp=_utc_now(),
                )
            )
            if provider == "openai" and path in _OPENAI_RESPONSES_PATHS:
                for tool_request in _extract_openai_tool_requests_from_response(
                    normalized_response.response
                ):
                    self._run.steps.append(
                        Step(
                            id=self._next_step_id(),
                            type="tool.request",
                            input=redact_listener_value(
                                {
                                    "tool": tool_request["tool"],
                                    "call_id": tool_request["call_id"],
                                    "arguments": tool_request["arguments"],
                                    "request_id": request.request_id,
                                }
                            ),
                            output=redact_listener_value(
                                {
                                    "status": "captured",
                                    "event": tool_request["event"],
                                }
                            ),
                            metadata=redact_listener_value(
                                {
                                    "provider": provider,
                                    "path": path,
                                    "request_id": request.request_id,
                                    "correlation_id": correlation_id,
                                    "capture_mode": "passive",
                                    "response_source": response_source,
                                    "derived_from": "openai.responses.response_output",
                                    "event_type": tool_request["type"],
                                }
                            ),
                            timestamp=_utc_now(),
                        )
                    )
            self._persist_locked()
            return status_code, response_payload

    def _stream_payload(
        self,
        *,
        request_id: str,
        correlation_id: str,
        normalized_response: ProviderResponse,
        status_code: int,
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for event in normalized_response.stream_events or []:
            if not isinstance(event, dict):
                continue
            event_payload = dict(event)
            event_payload["request_id"] = request_id
            event_payload["correlation_id"] = correlation_id
            events.append(event_payload)

        stream_enabled = bool(normalized_response.stream)
        stream_completed = bool(stream_enabled and status_code < 400)
        completion_state = "completed" if stream_completed else "incomplete"
        if not stream_enabled:
            completion_state = "not_streaming"

        diagnostics: list[dict[str, Any]] = []
        if stream_enabled and not stream_completed:
            diagnostics.append(
                {
                    "kind": "stream_incomplete",
                    "message": (
                        str((normalized_response.error or {}).get("message")).strip()
                        if isinstance(normalized_response.error, dict)
                        and (normalized_response.error or {}).get("message")
                        else "stream capture did not complete"
                    ),
                }
            )

        return {
            "enabled": stream_enabled,
            "completed": stream_completed,
            "completion_state": completion_state,
            "event_count": len(events),
            "events": redact_listener_value(events),
            "diagnostics": redact_listener_value(diagnostics),
        }

    def record_agent_payload(
        self,
        *,
        agent: str,
        payload: Any,
        initial_dropped: int = 0,
    ) -> tuple[int, int]:
        with self._lock:
            normalized_events, dropped = normalize_agent_events(agent=agent, payload=payload)
            dropped += max(0, initial_dropped)
            captured = 0
            for normalized_event in normalized_events:
                self._agent_event_sequence += 1
                request_id = normalized_event.get("request_id")
                if not request_id:
                    request_id = f"{agent}-event-{self._agent_event_sequence:06d}"
                metadata = dict(normalized_event["metadata"])
                metadata["request_id"] = request_id
                metadata["capture_mode"] = "passive"
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type=normalized_event["step_type"],
                        input=redact_listener_value(normalized_event["input"]),
                        output=redact_listener_value(normalized_event["output"]),
                        metadata=redact_listener_value(metadata),
                        timestamp=_utc_now(),
                    )
                )
                captured += 1

            if dropped > 0:
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type="error.event",
                        input={"agent": agent},
                        output={
                            "message": "dropped malformed or unsupported agent event frames",
                            "dropped": dropped,
                        },
                        metadata={
                            "agent": agent,
                            "event_type": "listener.drop",
                            "capture_mode": "passive",
                        },
                        timestamp=_utc_now(),
                    )
                )

            if captured > 0 or dropped > 0:
                self._persist_locked()
            return captured, dropped

    def record_internal_error(
        self,
        *,
        category: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._run.steps.append(
                Step(
                    id=self._next_step_id(),
                    type="error.event",
                    input={"source": "listener", "category": category},
                    output={
                        "message": message,
                        "details": redact_listener_value(details or {}),
                    },
                    metadata={
                        "source": "listener",
                        "category": category,
                        "capture_mode": "passive",
                    },
                    timestamp=_utc_now(),
                )
            )
            try:
                self._persist_locked()
            except Exception:
                return

    def _next_step_id(self) -> str:
        self._step_sequence += 1
        return f"step-{self._step_sequence:06d}"

    def _persist_locked(self) -> None:
        delay_raw = os.environ.get(_PERSIST_DELAY_ENV)
        if delay_raw:
            try:
                delay_seconds = float(delay_raw)
            except ValueError:
                delay_seconds = 0.0
            if delay_seconds > 0:
                time.sleep(min(delay_seconds, 5.0))
        write_artifact(
            self._run,
            self._out_path,
            metadata={
                "mode": "listener.passive",
                "listener_session_id": self._run.listener_session_id,
            },
        )


class _ReplayListenerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        # Avoid reverse-DNS lookup latency in HTTPServer.server_bind/getfqdn.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        session_id: str,
        state_file: Path,
        recorder: _ListenerRunRecorder | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.session_id = session_id
        self.state_file = state_file
        self.recorder = recorder
        self._metrics_lock = threading.Lock()
        self.capture_errors = 0
        self.dropped_events = 0
        self.degraded_responses = 0

    def register_capture_error(self) -> int:
        with self._metrics_lock:
            self.capture_errors += 1
            return self.capture_errors

    def register_dropped_events(self, count: int) -> int:
        with self._metrics_lock:
            self.dropped_events += max(0, count)
            return self.dropped_events

    def register_degraded_response(self) -> int:
        with self._metrics_lock:
            self.degraded_responses += 1
            return self.degraded_responses

    def metrics_payload(self) -> dict[str, int]:
        with self._metrics_lock:
            return {
                "capture_errors": self.capture_errors,
                "dropped_events": self.dropped_events,
                "degraded_responses": self.degraded_responses,
            }


class _ListenerHandler(BaseHTTPRequestHandler):
    server: _ReplayListenerServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        recorder = self.server.recorder
        if recorder is None:
            self._write_json(503, {"status": "error", "message": "recorder not ready"})
            return
        if parsed.path in {"/models", "/v1/models"}:
            try:
                status_code, response_body = recorder.record_provider_transaction(
                    provider="openai",
                    path=parsed.path,
                    query_params={
                        key: value
                        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                    },
                    payload={},
                    headers={str(key): str(value) for key, value in self.headers.items()},
                    fail_reason=None,
                )
            except Exception as error:
                capture_error_count = self.server.register_capture_error()
                degraded_sequence = self.server.register_degraded_response()
                recorder.record_internal_error(
                    category="capture_failure",
                    message="listener capture path failed; served degraded fallback response",
                    details={
                        "provider": "openai",
                        "path": parsed.path,
                        "error": str(error),
                        "capture_error_count": capture_error_count,
                    },
                )
                status_code, response_body = build_best_effort_fallback_response(
                    provider="openai",
                    sequence=degraded_sequence,
                )
                if status_code == 200:
                    response_body = build_openai_models_payload()
            self._write_json(status_code, response_body)
            return
        if parsed.path == "/health":
            self._write_json(
                200,
                {
                    "status": "ok",
                    "session_id": self.server.session_id,
                    "pid": os.getpid(),
                    "artifact_path": str(recorder.out_path),
                    "metrics": self.server.metrics_payload(),
                },
            )
            return
        self._write_json(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/shutdown":
            self._write_json(
                200,
                {"status": "ok", "message": "listener shutting down"},
            )

            def _shutdown() -> None:
                self.server.shutdown()

            threading.Thread(target=_shutdown, daemon=True).start()
            return

        agent = detect_agent(parsed.path)
        if agent is not None:
            recorder = self.server.recorder
            if recorder is None:
                self._write_json(503, {"status": "error", "message": "recorder not ready"})
                return
            payload, parse_error, parse_dropped = self._read_agent_body()
            captured, dropped = recorder.record_agent_payload(
                agent=agent,
                payload=payload,
                initial_dropped=parse_dropped,
            )
            if parse_error:
                recorder.record_internal_error(
                    category="agent_parse_failure",
                    message="listener agent payload parse failure; malformed frames dropped",
                    details={
                        "agent": agent,
                        "path": parsed.path,
                        "reason": parse_error,
                        "dropped_frames": parse_dropped,
                    },
                )
            if dropped > 0:
                self.server.register_dropped_events(dropped)
            self._write_json(
                202,
                {
                    "status": "ok",
                    "agent": agent,
                    "captured": captured,
                    "dropped": dropped,
                    "parse_error": parse_error,
                    "metrics": self.server.metrics_payload(),
                },
            )
            return

        provider = detect_provider(parsed.path)
        if provider is None:
            self._write_json(404, {"status": "error", "message": "unsupported path"})
            return

        recorder = self.server.recorder
        if recorder is None:
            self._write_json(503, {"status": "error", "message": "recorder not ready"})
            return

        payload, parse_error = self._read_json_body()
        fail_reason = self.headers.get("x-replaykit-fail")
        if parse_error and not fail_reason:
            fail_reason = parse_error
        if not isinstance(payload, dict):
            if not fail_reason:
                fail_reason = "non_object_json_body"
            payload = {"raw_payload": payload}

        try:
            force_capture_fail = (
                str(self.headers.get("x-replaykit-capture-fail", "")).strip().lower()
                in {"1", "true", "yes"}
            )
            if force_capture_fail:
                raise RuntimeError("simulated capture failure")
            status_code, response_body = recorder.record_provider_transaction(
                provider=provider,
                path=parsed.path,
                query_params={key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)},
                payload=payload,
                headers={str(key): str(value) for key, value in self.headers.items()},
                fail_reason=fail_reason,
            )
        except Exception as error:
            capture_error_count = self.server.register_capture_error()
            degraded_sequence = self.server.register_degraded_response()
            recorder.record_internal_error(
                category="capture_failure",
                message="listener capture path failed; served degraded fallback response",
                details={
                    "provider": provider,
                    "path": parsed.path,
                    "error": str(error),
                    "capture_error_count": capture_error_count,
                },
            )
            status_code, response_body = build_best_effort_fallback_response(
                provider=provider,
                sequence=degraded_sequence,
            )
            self._write_json(status_code, response_body)
            return

        if self._wants_openai_responses_sse(
            provider=provider,
            path=parsed.path,
            payload=payload,
            status_code=status_code,
        ):
            self._write_openai_responses_sse(response_body)
            return

        self._write_json(status_code, response_body)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> tuple[Any, str | None]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b""
        if not body:
            return {}, None
        decoded_body, decode_error = _decode_request_body(
            body=body,
            content_encoding=self.headers.get("Content-Encoding"),
        )
        if decode_error:
            return {"raw_body": body.decode("utf-8", errors="replace")}, decode_error

        decoded = decoded_body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            return {"raw_body": decoded}, "invalid_json_body"
        if isinstance(parsed, (dict, list)):
            return parsed, None
        return {"raw_body": decoded}, "non_object_json_body"

    def _read_agent_body(self) -> tuple[Any, str | None, int]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b""
        if not body:
            return {}, None, 0

        decoded = body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError:
            parsed_events: list[Any] = []
            dropped_frames = 0
            for line in decoded.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed_events.append(json.loads(stripped))
                except json.JSONDecodeError:
                    dropped_frames += 1

            if parsed_events:
                parse_error: str | None = None
                if dropped_frames > 0:
                    parse_error = "jsonl_partial_parse"
                return parsed_events, parse_error, dropped_frames

            return {"raw_body": decoded}, "invalid_json_body", max(1, dropped_frames)

        if isinstance(parsed, (dict, list)):
            return parsed, None, 0
        return {"raw_body": decoded}, "non_object_json_body", 1

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _wants_openai_responses_sse(
        self,
        *,
        provider: str,
        path: str,
        payload: dict[str, Any],
        status_code: int,
    ) -> bool:
        if status_code >= 400:
            return False
        if provider != "openai" or path not in {"/responses", "/v1/responses"}:
            return False
        accept = str(self.headers.get("Accept", "")).lower()
        if "text/event-stream" in accept:
            return True
        return bool(payload.get("stream"))

    def _write_openai_responses_sse(self, payload: dict[str, Any]) -> None:
        response_id = str(payload.get("id") or f"resp-listener-{int(time.time() * 1000)}")
        model = str(payload.get("model") or "gpt-4o-mini")
        output_text = str(payload.get("output_text") or "")
        if not output_text:
            output = payload.get("output")
            if (
                isinstance(output, list)
                and output
                and isinstance(output[0], dict)
                and isinstance(output[0].get("content"), list)
                and output[0]["content"]
                and isinstance(output[0]["content"][0], dict)
                and isinstance(output[0]["content"][0].get("text"), str)
            ):
                output_text = output[0]["content"][0]["text"]
        message_id = f"msg-{response_id}"
        completed_item = {
            "id": message_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": output_text,
                    "annotations": [],
                }
            ],
        }
        completed_response = {
            "id": response_id,
            "object": "response",
            "status": "completed",
            "model": model,
            "output": [completed_item],
            "output_text": output_text,
        }
        events: list[dict[str, Any]] = [
            {
                "type": "response.created",
                "response": {
                    "id": response_id,
                    "object": "response",
                    "status": "in_progress",
                    "model": model,
                },
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": message_id,
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                },
            },
            {
                "type": "response.content_part.added",
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": ""},
            },
        ]
        for chunk in _split_stream_text(output_text):
            events.append(
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": chunk,
                }
            )
        events.extend(
            [
                {
                    "type": "response.output_text.done",
                    "output_index": 0,
                    "content_index": 0,
                    "text": output_text,
                },
                {
                    "type": "response.content_part.done",
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": output_text},
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": completed_item,
                },
                {
                    "type": "response.completed",
                    "response": completed_response,
                },
            ]
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            frame = f"data: {json.dumps(event, ensure_ascii=True, separators=(',', ':'))}\n\n"
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m replaypack.listener_daemon",
        description="ReplayKit passive listener daemon process.",
    )
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--out",
        default=Path("runs/listener/listener-capture.rpk"),
        type=Path,
    )
    parser.add_argument(
        "--payload-string-limit",
        default=_resolve_payload_string_limit(),
        type=int,
        help="Max string length for captured request payload values (0 disables truncation).",
    )
    parser.add_argument(
        "--fail-on-synthetic",
        action="store_true",
        help="Block synthetic fallback responses when live upstream forwarding is unavailable.",
    )
    return parser


def _decode_request_body(*, body: bytes, content_encoding: str | None) -> tuple[bytes, str | None]:
    if not content_encoding:
        return body, None
    encodings = [entry.strip().lower() for entry in content_encoding.split(",") if entry.strip()]
    if not encodings:
        return body, None

    decoded = body
    for encoding in reversed(encodings):
        try:
            if encoding == "identity":
                continue
            if encoding == "gzip":
                decoded = gzip.decompress(decoded)
                continue
            if encoding == "deflate":
                try:
                    decoded = zlib.decompress(decoded)
                except zlib.error:
                    decoded = zlib.decompress(decoded, -zlib.MAX_WBITS)
                continue
            if encoding == "zstd":
                if zstd is None:
                    return body, "unsupported_content_encoding:zstd"
                decoded, decode_error = _decode_zstd(decoded)
                if decode_error:
                    return body, decode_error
                continue
        except Exception:
            return body, f"invalid_content_encoding:{encoding}"
        return body, f"unsupported_content_encoding:{encoding}"
    return decoded, None


def _decode_zstd(body: bytes) -> tuple[bytes, str | None]:
    if zstd is None:
        return body, "unsupported_content_encoding:zstd"
    decompressor = zstd.ZstdDecompressor()
    try:
        return decompressor.decompress(body), None
    except Exception:
        try:
            with decompressor.stream_reader(io.BytesIO(body)) as reader:
                return reader.read(), None
        except Exception:
            return body, "invalid_content_encoding:zstd"


def _split_stream_text(text: str, chunk_size: int = 5) -> list[str]:
    if not text:
        return []
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


def _runtime_payload(
    *,
    session_id: str,
    host: str,
    port: int,
    out_path: Path,
    allow_synthetic: bool,
    payload_string_limit: int,
) -> dict[str, Any]:
    return {
        "status": "running",
        "listener_session_id": session_id,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "artifact_path": str(out_path),
        "allow_synthetic": allow_synthetic,
        "synthetic_policy": "allow" if allow_synthetic else "fail_closed",
        "payload_string_limit": payload_string_limit,
        "full_payload_capture": payload_string_limit <= 0,
        "started_at": _utc_now(),
        "process": {
            "pid": os.getpid(),
            "executable": sys.executable,
            "command": list(sys.argv),
            "cwd": str(Path.cwd()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    server: _ReplayListenerServer | None = None

    try:
        server = _ReplayListenerServer(
            (args.host, args.port),
            _ListenerHandler,
            session_id=args.session_id,
            state_file=args.state_file,
            recorder=None,
        )
    except OSError as error:
        print(f"listener daemon failed: {error}", file=sys.stderr)
        return 1

    host, port = server.server_address[0], int(server.server_address[1])
    server.recorder = _ListenerRunRecorder(
        session_id=args.session_id,
        out_path=args.out,
        host=host,
        port=port,
        allow_synthetic=not bool(args.fail_on_synthetic),
        payload_string_limit=max(0, int(args.payload_string_limit)),
    )
    write_listener_state(
        args.state_file,
        _runtime_payload(
            session_id=args.session_id,
            host=host,
            port=port,
            out_path=args.out,
            allow_synthetic=not bool(args.fail_on_synthetic),
            payload_string_limit=max(0, int(args.payload_string_limit)),
        ),
    )

    def _handle_signal(_signum: int, _frame: Any) -> None:
        if server is not None:
            server.shutdown()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        remove_listener_state(args.state_file)
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
