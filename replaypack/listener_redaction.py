"""Listener-specific redaction helpers."""

from __future__ import annotations

from typing import Any

from replaypack.capture import DEFAULT_REDACTION_POLICY, RedactionPolicy, redact_payload

_SENSITIVE_HEADER_TOKENS = ("auth", "token", "secret", "key")
_ALLOWED_HEADER_KEYS = {
    "accept",
    "content-type",
    "user-agent",
    "x-request-id",
}


def redact_listener_headers(
    headers: dict[str, Any],
    *,
    policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        if _header_is_sensitive(key, policy=policy):
            redacted[key] = policy.mask
            continue
        redacted[key] = redact_payload(raw_value, policy=policy)
    return redacted


def redact_listener_value(
    value: Any,
    *,
    policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
) -> Any:
    return redact_payload(value, policy=policy)


def _header_is_sensitive(key: str, *, policy: RedactionPolicy) -> bool:
    if key in policy.sensitive_field_names:
        return True
    if key in _ALLOWED_HEADER_KEYS:
        return False
    return any(token in key for token in _SENSITIVE_HEADER_TOKENS)
