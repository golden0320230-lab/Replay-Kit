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
_UPSTREAM_RETRIES_ENV = "REPLAYKIT_LISTENER_UPSTREAM_RETRIES"
_UPSTREAM_RETRY_BACKOFF_ENV = "REPLAYKIT_LISTENER_UPSTREAM_RETRY_BACKOFF_SECONDS"
_UPSTREAM_DEFAULT_TIMEOUT_SECONDS = 5.0
_UPSTREAM_DEFAULT_RETRIES = 0
_UPSTREAM_DEFAULT_RETRY_BACKOFF_SECONDS = 0.25
_PAYLOAD_STRING_LIMIT_ENV = "REPLAYKIT_LISTENER_PAYLOAD_STRING_LIMIT"
_PAYLOAD_STRING_DEFAULT_LIMIT = 4096
_FALLBACK_POLICY_SYNTHETIC_ALLOWED = "synthetic_allowed"
_FALLBACK_POLICY_BEST_EFFORT = "best_effort"
_FALLBACK_POLICY_LIVE_ONLY = "live_only"
_FALLBACK_POLICIES = {
    _FALLBACK_POLICY_SYNTHETIC_ALLOWED,
    _FALLBACK_POLICY_BEST_EFFORT,
    _FALLBACK_POLICY_LIVE_ONLY,
}
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
_SUPPORTED_ROUTE_MATRIX: dict[str, tuple[str, ...]] = {
    "GET": ("/health", "/models", "/v1/models"),
    "POST": (
        "/shutdown",
        "/responses",
        "/v1/responses",
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/messages",
        "/messages",
        "/v1beta/models/{model}:generateContent",
        "/agent/codex/events",
        "/agent/claude-code/events",
    ),
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


def _resolve_upstream_retries() -> int:
    raw = os.environ.get(_UPSTREAM_RETRIES_ENV)
    if raw is None:
        return _UPSTREAM_DEFAULT_RETRIES
    try:
        parsed = int(raw)
    except ValueError:
        return _UPSTREAM_DEFAULT_RETRIES
    return max(0, min(parsed, 5))


def _resolve_upstream_retry_backoff_seconds() -> float:
    raw = os.environ.get(_UPSTREAM_RETRY_BACKOFF_ENV)
    if raw is None:
        return _UPSTREAM_DEFAULT_RETRY_BACKOFF_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _UPSTREAM_DEFAULT_RETRY_BACKOFF_SECONDS
    return max(0.0, min(parsed, 5.0))


def _resolve_payload_string_limit() -> int:
    raw = os.environ.get(_PAYLOAD_STRING_LIMIT_ENV)
    if raw is None:
        return _PAYLOAD_STRING_DEFAULT_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return _PAYLOAD_STRING_DEFAULT_LIMIT
    return max(0, parsed)


def _normalize_route_path(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        return "/"
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized or "/"


def _route_response_for_unsupported(method: str, path: str) -> tuple[int, dict[str, Any]]:
    normalized_method = method.upper().strip()
    normalized_path = _normalize_route_path(path)
    supported_for_method = _SUPPORTED_ROUTE_MATRIX.get(normalized_method, ())
    for allowed_method, routes in _SUPPORTED_ROUTE_MATRIX.items():
        if allowed_method == normalized_method:
            continue
        if normalized_path in routes:
            return 405, {
                "status": "error",
                "code": "method_not_allowed",
                "message": (
                    f"{normalized_method} is not supported for route '{normalized_path}'. "
                    f"Use {allowed_method}."
                ),
                "method": normalized_method,
                "path": normalized_path,
                "supported_methods": [allowed_method],
                "hint": "Run `python3 -m replaypack listen status --json` to confirm listener health.",
            }

    return 404, {
        "status": "error",
        "code": "unsupported_route",
        "message": f"unsupported route: {normalized_method} {normalized_path}",
        "method": normalized_method,
        "path": normalized_path,
        "supported_paths": list(supported_for_method),
        "hint": (
            "Run `python3 -m replaypack listen env --state-file <state> --shell bash` "
            "and route supported provider paths through the listener."
        ),
    }


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
    retries: int,
    retry_backoff_seconds: float,
) -> tuple[int, dict[str, Any], str | None, int]:
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
    attempts = max(1, int(retries) + 1)
    opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        request = urllib_request.Request(
            target_url,
            data=body,
            headers=forward_headers,
            method="POST",
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status_code = int(response.status)
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as error:
            status_code = int(error.code)
            raw_body = error.read().decode("utf-8")
            if status_code >= 500 and attempt < attempts:
                sleep_seconds = retry_backoff_seconds * attempt
                if sleep_seconds > 0:
                    time.sleep(min(sleep_seconds, 5.0))
                continue
        except (urllib_error.URLError, TimeoutError, OSError, ValueError) as error:
            last_error = str(error)
            if attempt < attempts:
                sleep_seconds = retry_backoff_seconds * attempt
                if sleep_seconds > 0:
                    time.sleep(min(sleep_seconds, 5.0))
                continue
            return 0, {}, last_error, attempt

        if not raw_body:
            parsed_body: dict[str, Any] = {}
        else:
            try:
                parsed_payload = json.loads(raw_body)
            except json.JSONDecodeError:
                return 0, {}, "upstream returned non-JSON response body", attempt
            if not isinstance(parsed_payload, dict):
                return 0, {}, "upstream returned non-object JSON response body", attempt
            parsed_body = parsed_payload
        return status_code, parsed_body, None, attempt

    return 0, {}, last_error or "upstream request failed", attempts


class _ListenerRunRecorder:
    def __init__(
        self,
        *,
        session_id: str,
        out_path: Path,
        host: str,
        port: int,
        fallback_policy: str,
        payload_string_limit: int,
        upstream_timeout_seconds: float,
        upstream_retries: int,
        upstream_retry_backoff_seconds: float,
    ) -> None:
        self._lock = threading.Lock()
        self._out_path = out_path
        normalized_policy = str(fallback_policy).strip().lower()
        if normalized_policy not in _FALLBACK_POLICIES:
            normalized_policy = _FALLBACK_POLICY_SYNTHETIC_ALLOWED
        self._fallback_policy = normalized_policy
        self._payload_string_limit = max(0, int(payload_string_limit))
        self._upstream_timeout_seconds = max(0.1, min(float(upstream_timeout_seconds), 120.0))
        self._upstream_retries = max(0, min(int(upstream_retries), 5))
        self._upstream_retry_backoff_seconds = max(
            0.0, min(float(upstream_retry_backoff_seconds), 5.0)
        )
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

    @property
    def fallback_policy(self) -> str:
        return self._fallback_policy

    @property
    def allow_synthetic(self) -> bool:
        return self._fallback_policy == _FALLBACK_POLICY_SYNTHETIC_ALLOWED

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
            policy_outcome = "synthetic_response"
            synthetic_block_reason: str | None = None
            best_effort_reason: str | None = None
            upstream_attempts = 0
            upstream_base_url = _resolve_provider_upstream_base_url(provider)
            supports_upstream_forward = path not in {"/models", "/v1/models"}

            if fail_reason:
                if self._fallback_policy == _FALLBACK_POLICY_LIVE_ONLY:
                    response_source = "synthetic_blocked"
                    policy_outcome = "live_only_blocked"
                    synthetic_block_reason = str(fail_reason)
                    status_code, response_payload, normalized_response = build_provider_response(
                        request=request,
                        sequence=self._request_sequence,
                        fail_reason=(
                            "synthetic_fallback_blocked_by_policy: "
                            f"{synthetic_block_reason}"
                        ),
                    )
                elif self._fallback_policy == _FALLBACK_POLICY_BEST_EFFORT:
                    response_source = "best_effort_fallback"
                    policy_outcome = "best_effort_fallback"
                    best_effort_reason = str(fail_reason)
                    status_code, response_payload = build_best_effort_fallback_response(
                        provider=provider,
                        sequence=self._request_sequence,
                    )
                    normalized_response = normalize_provider_response(
                        provider=provider,
                        status_code=status_code,
                        payload=response_payload,
                        stream=request.stream,
                        path=path,
                    )
                else:
                    response_source = "synthetic"
                    policy_outcome = "synthetic_error"
                    status_code, response_payload, normalized_response = build_provider_response(
                        request=request,
                        sequence=self._request_sequence,
                        fail_reason=fail_reason,
                    )
            else:
                if upstream_base_url and supports_upstream_forward:
                    response_source = "upstream"
                    (
                        status_code,
                        response_payload,
                        upstream_error,
                        upstream_attempts,
                    ) = _forward_provider_request(
                        upstream_base_url=upstream_base_url,
                        path=path,
                        payload=request.payload,
                        headers=request.headers,
                        timeout_seconds=self._upstream_timeout_seconds,
                        retries=self._upstream_retries,
                        retry_backoff_seconds=self._upstream_retry_backoff_seconds,
                    )
                    if upstream_error:
                        upstream_failure_reason = f"upstream_forward_failed: {upstream_error}"
                        if self._fallback_policy == _FALLBACK_POLICY_BEST_EFFORT:
                            response_source = "best_effort_fallback"
                            policy_outcome = "best_effort_fallback"
                            best_effort_reason = upstream_failure_reason
                            status_code, response_payload = build_best_effort_fallback_response(
                                provider=provider,
                                sequence=self._request_sequence,
                            )
                            normalized_response = normalize_provider_response(
                                provider=provider,
                                status_code=status_code,
                                payload=response_payload,
                                stream=request.stream,
                                path=path,
                            )
                        elif self._fallback_policy == _FALLBACK_POLICY_LIVE_ONLY:
                            response_source = "synthetic_blocked"
                            policy_outcome = "live_only_blocked"
                            synthetic_block_reason = upstream_failure_reason
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
                            response_source = "upstream_error"
                            policy_outcome = "synthetic_error"
                            status_code, response_payload, normalized_response = (
                                build_provider_response(
                                    request=request,
                                    sequence=self._request_sequence,
                                    fail_reason=upstream_failure_reason,
                                )
                            )
                    else:
                        response_source = "upstream"
                        policy_outcome = "live_upstream"
                        normalized_response = normalize_provider_response(
                            provider=provider,
                            status_code=status_code,
                            payload=response_payload,
                            path=path,
                        )
                else:
                    if supports_upstream_forward and self._fallback_policy == _FALLBACK_POLICY_LIVE_ONLY:
                        response_source = "synthetic_blocked"
                        policy_outcome = "live_only_blocked"
                        synthetic_block_reason = "no_upstream_configured"
                        status_code, response_payload, normalized_response = build_provider_response(
                            request=request,
                            sequence=self._request_sequence,
                            fail_reason=(
                                "synthetic_fallback_blocked_by_policy: "
                                f"{synthetic_block_reason}"
                            ),
                        )
                    elif supports_upstream_forward and self._fallback_policy == _FALLBACK_POLICY_BEST_EFFORT:
                        response_source = "best_effort_fallback"
                        policy_outcome = "best_effort_fallback"
                        best_effort_reason = "no_upstream_configured"
                        status_code, response_payload = build_best_effort_fallback_response(
                            provider=provider,
                            sequence=self._request_sequence,
                        )
                        normalized_response = normalize_provider_response(
                            provider=provider,
                            status_code=status_code,
                            payload=response_payload,
                            stream=request.stream,
                            path=path,
                        )
                    else:
                        response_source = "synthetic"
                        policy_outcome = "synthetic_response"
                        status_code, response_payload, normalized_response = build_provider_response(
                            request=request,
                            sequence=self._request_sequence,
                            fail_reason=None,
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
                            "fallback_policy": self._fallback_policy,
                            "policy_outcome": policy_outcome,
                            "response_source": response_source,
                            "upstream_base_url": upstream_base_url,
                            "upstream_attempts": upstream_attempts,
                            "upstream_timeout_seconds": self._upstream_timeout_seconds,
                            "upstream_retries": self._upstream_retries,
                            "upstream_retry_backoff_seconds": self._upstream_retry_backoff_seconds,
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
                                    "fallback_policy": self._fallback_policy,
                                    "policy_outcome": policy_outcome,
                                    "upstream_base_url": upstream_base_url,
                                    "upstream_attempts": upstream_attempts,
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
                                "fallback_policy": self._fallback_policy,
                                "policy_outcome": policy_outcome,
                            }
                        ),
                        timestamp=_utc_now(),
                    )
                )
            if best_effort_reason is not None:
                self._run.steps.append(
                    Step(
                        id=self._next_step_id(),
                        type="error.event",
                        input=redact_listener_value(
                            {
                                "source": "listener",
                                "category": "best_effort_fallback",
                                "request_id": request.request_id,
                            }
                        ),
                        output=redact_listener_value(
                            {
                                "message": "best-effort fallback applied after upstream/capture failure",
                                "details": {
                                    "provider": provider,
                                    "path": path,
                                    "request_id": request.request_id,
                                    "reason": best_effort_reason,
                                    "fallback_policy": self._fallback_policy,
                                    "policy_outcome": policy_outcome,
                                    "upstream_base_url": upstream_base_url,
                                    "upstream_attempts": upstream_attempts,
                                },
                            }
                        ),
                        metadata=redact_listener_value(
                            {
                                "source": "listener",
                                "category": "best_effort_fallback",
                                "provider": provider,
                                "path": path,
                                "request_id": request.request_id,
                                "correlation_id": correlation_id,
                                "capture_mode": "passive",
                                "fallback_policy": self._fallback_policy,
                                "policy_outcome": policy_outcome,
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
                            "fallback_policy": self._fallback_policy,
                            "policy_outcome": policy_outcome,
                            "response_source": response_source,
                            "upstream_base_url": upstream_base_url,
                            "upstream_attempts": upstream_attempts,
                            "upstream_timeout_seconds": self._upstream_timeout_seconds,
                            "upstream_retries": self._upstream_retries,
                            "upstream_retry_backoff_seconds": self._upstream_retry_backoff_seconds,
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
        event_types: list[str] = []
        for event in normalized_response.stream_events or []:
            if not isinstance(event, dict):
                continue
            event_payload = dict(event)
            event_payload["request_id"] = request_id
            event_payload["correlation_id"] = correlation_id
            events.append(event_payload)
            event_type = str(
                event_payload.get("provider_event_type")
                or event_payload.get("type")
                or ""
            ).strip()
            if event_type:
                event_types.append(event_type)

        terminal_event_type = ""
        for event in reversed(events):
            if not bool(event.get("terminal")):
                continue
            event_type = str(
                event.get("provider_event_type")
                or event.get("type")
                or ""
            ).strip()
            if event_type:
                terminal_event_type = event_type
            break

        stream_enabled = bool(normalized_response.stream)
        stream_outcome = "completed"
        if not stream_enabled:
            stream_outcome = "not_streaming"
        elif status_code >= 400:
            stream_outcome = "errored"
        elif terminal_event_type:
            stream_outcome = "completed"
        else:
            stream_outcome = "interrupted"

        stream_completed = bool(stream_outcome == "completed")
        completion_state = "completed" if stream_completed else "incomplete"
        if not stream_enabled:
            completion_state = "not_streaming"

        diagnostics: list[dict[str, Any]] = []
        if stream_enabled and stream_outcome != "completed":
            diagnostics.append(
                {
                    "kind": "stream_incomplete",
                    "outcome": stream_outcome,
                    "terminal_event_type": terminal_event_type or None,
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
            "outcome": stream_outcome,
            "event_count": len(events),
            "events": redact_listener_value(events),
            "event_types": redact_listener_value(event_types),
            "terminal_event_type": redact_listener_value(terminal_event_type),
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
        normalized_path = _normalize_route_path(parsed.path)
        recorder = self.server.recorder
        if recorder is None:
            self._write_json(503, {"status": "error", "message": "recorder not ready"})
            return
        if normalized_path in {"/models", "/v1/models"}:
            try:
                status_code, response_body = recorder.record_provider_transaction(
                    provider="openai",
                    path=normalized_path,
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
                internal_message = "listener capture path failed; served degraded fallback response"
                policy_outcome = "live_only_error"
                if recorder.fallback_policy == _FALLBACK_POLICY_LIVE_ONLY:
                    internal_message = "listener capture path failed; live_only returned strict error"
                    status_code = 502
                    response_body = {
                        "error": {
                            "type": "listener_capture_error",
                            "message": (
                                "listener capture path failed and fallback policy live_only "
                                "forbids degraded/synthetic responses"
                            ),
                            "policy": recorder.fallback_policy,
                        }
                    }
                else:
                    policy_outcome = "best_effort_fallback"
                    degraded_sequence = self.server.register_degraded_response()
                    status_code, response_body = build_best_effort_fallback_response(
                        provider="openai",
                        sequence=degraded_sequence,
                    )
                    if status_code == 200:
                        response_body = build_openai_models_payload()
                recorder.record_internal_error(
                    category="capture_failure",
                    message=internal_message,
                    details={
                        "provider": "openai",
                        "path": normalized_path,
                        "error": str(error),
                        "capture_error_count": capture_error_count,
                        "fallback_policy": recorder.fallback_policy,
                        "policy_outcome": policy_outcome,
                    },
                )
            self._write_json(status_code, response_body)
            return
        if normalized_path == "/health":
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
        status_code, payload = _route_response_for_unsupported("GET", normalized_path)
        self._write_json(status_code, payload)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        normalized_path = _normalize_route_path(parsed.path)
        if normalized_path == "/shutdown":
            self._write_json(
                200,
                {"status": "ok", "message": "listener shutting down"},
            )

            def _shutdown() -> None:
                self.server.shutdown()

            threading.Thread(target=_shutdown, daemon=True).start()
            return

        if normalized_path in {"/models", "/v1/models"}:
            status_code, payload = _route_response_for_unsupported("POST", normalized_path)
            self._write_json(status_code, payload)
            return

        agent = detect_agent(normalized_path)
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
                        "path": normalized_path,
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

        provider = detect_provider(normalized_path)
        if provider is None:
            status_code, payload = _route_response_for_unsupported("POST", normalized_path)
            self._write_json(status_code, payload)
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
                path=normalized_path,
                query_params={key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)},
                payload=payload,
                headers={str(key): str(value) for key, value in self.headers.items()},
                fail_reason=fail_reason,
            )
        except Exception as error:
            capture_error_count = self.server.register_capture_error()
            internal_message = "listener capture path failed; served degraded fallback response"
            policy_outcome = "live_only_error"
            if recorder.fallback_policy == _FALLBACK_POLICY_LIVE_ONLY:
                internal_message = "listener capture path failed; live_only returned strict error"
                status_code = 502
                response_body = {
                    "error": {
                        "type": "listener_capture_error",
                        "message": (
                            "listener capture path failed and fallback policy live_only "
                            "forbids degraded/synthetic responses"
                        ),
                        "policy": recorder.fallback_policy,
                    }
                }
            else:
                policy_outcome = "best_effort_fallback"
                degraded_sequence = self.server.register_degraded_response()
                status_code, response_body = build_best_effort_fallback_response(
                    provider=provider,
                    sequence=degraded_sequence,
                )
            recorder.record_internal_error(
                category="capture_failure",
                message=internal_message,
                details={
                    "provider": provider,
                    "path": normalized_path,
                    "error": str(error),
                    "capture_error_count": capture_error_count,
                    "fallback_policy": recorder.fallback_policy,
                    "policy_outcome": policy_outcome,
                },
            )
            self._write_json(status_code, response_body)
            return

        if self._wants_openai_responses_sse(
            provider=provider,
            path=normalized_path,
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
        "--fallback-policy",
        default=_FALLBACK_POLICY_SYNTHETIC_ALLOWED,
        choices=sorted(_FALLBACK_POLICIES),
        help=(
            "Fallback policy when live upstream forwarding is unavailable or fails: "
            "synthetic_allowed, best_effort, or live_only."
        ),
    )
    parser.add_argument(
        "--upstream-timeout-seconds",
        default=_resolve_upstream_timeout_seconds(),
        type=float,
        help="Timeout in seconds for each upstream provider request attempt.",
    )
    parser.add_argument(
        "--upstream-retries",
        default=_resolve_upstream_retries(),
        type=int,
        help="Number of upstream retry attempts for transport errors or HTTP 5xx responses.",
    )
    parser.add_argument(
        "--upstream-retry-backoff-seconds",
        default=_resolve_upstream_retry_backoff_seconds(),
        type=float,
        help="Linear backoff base seconds applied between upstream retries.",
    )
    parser.add_argument(
        "--fail-on-synthetic",
        action="store_true",
        help="Deprecated alias for --fallback-policy live_only.",
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
    fallback_policy: str,
    payload_string_limit: int,
    upstream_timeout_seconds: float,
    upstream_retries: int,
    upstream_retry_backoff_seconds: float,
) -> dict[str, Any]:
    normalized_policy = str(fallback_policy).strip().lower()
    allow_synthetic = normalized_policy == _FALLBACK_POLICY_SYNTHETIC_ALLOWED
    return {
        "status": "running",
        "listener_session_id": session_id,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "artifact_path": str(out_path),
        "allow_synthetic": allow_synthetic,
        "synthetic_policy": "allow" if allow_synthetic else "fail_closed",
        "fallback_policy": normalized_policy,
        "upstream_timeout_seconds": upstream_timeout_seconds,
        "upstream_retries": upstream_retries,
        "upstream_retry_backoff_seconds": upstream_retry_backoff_seconds,
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
    fallback_policy = str(args.fallback_policy).strip().lower()
    if args.fail_on_synthetic:
        fallback_policy = _FALLBACK_POLICY_LIVE_ONLY
    if fallback_policy not in _FALLBACK_POLICIES:
        fallback_policy = _FALLBACK_POLICY_SYNTHETIC_ALLOWED

    upstream_timeout_seconds = max(0.1, min(float(args.upstream_timeout_seconds), 120.0))
    upstream_retries = max(0, min(int(args.upstream_retries), 5))
    upstream_retry_backoff_seconds = max(0.0, min(float(args.upstream_retry_backoff_seconds), 5.0))

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
        fallback_policy=fallback_policy,
        payload_string_limit=max(0, int(args.payload_string_limit)),
        upstream_timeout_seconds=upstream_timeout_seconds,
        upstream_retries=upstream_retries,
        upstream_retry_backoff_seconds=upstream_retry_backoff_seconds,
    )
    write_listener_state(
        args.state_file,
        _runtime_payload(
            session_id=args.session_id,
            host=host,
            port=port,
            out_path=args.out,
            fallback_policy=fallback_policy,
            payload_string_limit=max(0, int(args.payload_string_limit)),
            upstream_timeout_seconds=upstream_timeout_seconds,
            upstream_retries=upstream_retries,
            upstream_retry_backoff_seconds=upstream_retry_backoff_seconds,
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
