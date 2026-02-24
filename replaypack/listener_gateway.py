"""Provider gateway normalization for passive listener mode."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any


_SUPPORTED_PROVIDERS = ("openai", "anthropic", "google")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    provider: str
    path: str
    model: str | None
    stream: bool
    payload: dict[str, Any]
    headers: dict[str, str]
    request_id: str


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider: str
    status_code: int
    response: dict[str, Any]
    assembled_text: str
    stream: bool = False
    stream_events: list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None


def detect_provider(path: str) -> str | None:
    normalized = path.strip()
    if normalized in {"/responses", "/v1/responses"}:
        return "openai"
    if normalized == "/v1/chat/completions":
        return "openai"
    if normalized == "/v1/messages":
        return "anthropic"
    if normalized.startswith("/v1beta/models/") and normalized.endswith(":generateContent"):
        return "google"
    return None


def normalize_provider_request(
    *,
    provider: str,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    request_id: str,
) -> ProviderRequest:
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    model = _extract_model(provider, payload, path=path)
    stream = bool(payload.get("stream", False))
    normalized_headers = {
        key.lower(): str(value)
        for key, value in sorted(headers.items(), key=lambda item: str(item[0]).lower())
        if key and key.lower() not in {"content-length", "connection", "host"}
    }
    return ProviderRequest(
        provider=provider,
        path=path,
        model=model,
        stream=stream,
        payload=_stable_object_copy(payload),
        headers=normalized_headers,
        request_id=request_id,
    )


def build_provider_response(
    *,
    request: ProviderRequest,
    sequence: int,
    fail_reason: str | None = None,
) -> tuple[int, dict[str, Any], ProviderResponse]:
    if fail_reason:
        status = 502
        body = {
            "error": {
                "type": "listener_gateway_error",
                "message": fail_reason,
                "provider": request.provider,
            }
        }
        normalized = ProviderResponse(
            provider=request.provider,
            status_code=status,
            response=body,
            assembled_text="",
            stream=request.stream,
            stream_events=[],
            error={"type": "gateway_error", "message": fail_reason},
        )
        return status, body, normalized

    text = "ReplayKit listener response"
    if request.provider == "openai":
        if request.path in {"/responses", "/v1/responses"}:
            response = {
                "id": f"resp-listener-{sequence:06d}",
                "object": "response",
                "status": "completed",
                "model": request.model or "gpt-4o-mini",
                "output": [
                    {
                        "id": f"msg-listener-{sequence:06d}",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": text,
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "output_text": text,
            }
        else:
            response = {
                "id": f"chatcmpl-listener-{sequence:06d}",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": text}}],
            }
    elif request.provider == "anthropic":
        response = {
            "id": f"msg-listener-{sequence:06d}",
            "type": "message",
            "content": [{"type": "text", "text": text}],
        }
    else:
        response = {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": text}],
                    }
                }
            ]
        }
    normalized = normalize_provider_response(
        provider=request.provider,
        status_code=200,
        payload=response,
        stream=request.stream,
    )
    return 200, response, normalized


def build_best_effort_fallback_response(
    *,
    provider: str,
    sequence: int,
) -> tuple[int, dict[str, Any]]:
    text = "ReplayKit capture degraded fallback response"
    if provider == "openai":
        body = {
            "id": f"chatcmpl-fallback-{sequence:06d}",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "_replaykit": {"capture_status": "degraded"},
        }
    elif provider == "anthropic":
        body = {
            "id": f"msg-fallback-{sequence:06d}",
            "type": "message",
            "content": [{"type": "text", "text": text}],
            "_replaykit": {"capture_status": "degraded"},
        }
    else:
        body = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": text}]}}
            ],
            "_replaykit": {"capture_status": "degraded"},
        }
    return 200, body


def normalize_provider_response(
    *,
    provider: str,
    status_code: int,
    payload: dict[str, Any],
    stream: bool = False,
) -> ProviderResponse:
    assembled_text = _extract_text(provider, payload)
    error_payload = None
    if status_code >= 400:
        error_payload = {"status_code": status_code, "payload": dict(payload)}
    stream_events: list[dict[str, Any]] = []
    if stream and status_code < 400 and assembled_text:
        stream_events = _synthesize_stream_events(provider=provider, assembled_text=assembled_text)
    return ProviderResponse(
        provider=provider,
        status_code=status_code,
        response=_stable_object_copy(payload),
        assembled_text=assembled_text,
        stream=stream,
        stream_events=stream_events,
        error=error_payload,
    )


def provider_request_fingerprint(request: ProviderRequest) -> str:
    digest = hashlib.sha256(
        (
            f"{request.provider}|{request.path}|{request.model}|"
            f"{request.stream}|{request.request_id}"
        ).encode("utf-8")
    ).hexdigest()
    return f"req-{digest[:16]}"


def _stable_object_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_object_copy(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_stable_object_copy(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_object_copy(item) for item in value]
    return value


def _extract_model(provider: str, payload: dict[str, Any], *, path: str) -> str | None:
    if provider in {"openai", "anthropic"}:
        model = payload.get("model")
        return str(model) if isinstance(model, str) else None
    if provider == "google":
        model = payload.get("model")
        if isinstance(model, str):
            return model
        path_parts = path.split("/")
        if len(path_parts) >= 4:
            model_segment = path_parts[3]
            if model_segment:
                return model_segment
    return None


def _extract_text(provider: str, payload: dict[str, Any]) -> str:
    if provider == "openai":
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
    if provider == "anthropic":
        content = payload.get("content")
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "".join(chunks)
    if provider == "google":
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                content = first.get("content")
                if isinstance(content, dict):
                    parts = content.get("parts")
                    if isinstance(parts, list):
                        chunks = []
                        for part in parts:
                            if isinstance(part, dict):
                                text = part.get("text")
                                if isinstance(text, str):
                                    chunks.append(text)
                        return "".join(chunks)
    return ""


def _synthesize_stream_events(*, provider: str, assembled_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, chunk in enumerate(_split_stream_chunks(assembled_text), start=1):
        events.append(
            {
                "index": index,
                "provider": provider,
                "delta_text": chunk,
            }
        )
    return events


def _split_stream_chunks(text: str, chunk_size: int = 3) -> list[str]:
    if not text:
        return []
    return [text[idx : idx + chunk_size] for idx in range(0, len(text), chunk_size)]
