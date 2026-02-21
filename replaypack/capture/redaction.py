"""Security-first redaction policy for capture payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "apikey",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "set-cookie",
        "cookie",
    }
)

SAFE_FIELD_NAMES = frozenset(
    {
        "tool",
        "model",
        "provider",
        "method",
        "url",
        "status",
        "status_code",
        "name",
        "host",
        "path",
    }
)

SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
)


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Redaction policy for masking sensitive fields and values."""

    version: str = "1.0"
    enabled: bool = True
    mask: str = "[REDACTED]"
    sensitive_field_names: frozenset[str] = field(default_factory=lambda: SENSITIVE_FIELD_NAMES)
    safe_field_names: frozenset[str] = field(default_factory=lambda: SAFE_FIELD_NAMES)


DEFAULT_REDACTION_POLICY = RedactionPolicy()


def redact_payload(value: Any, *, policy: RedactionPolicy = DEFAULT_REDACTION_POLICY) -> Any:
    if not policy.enabled:
        return value
    return _redact(value, path=(), policy=policy)


def _redact(value: Any, *, path: tuple[str, ...], policy: RedactionPolicy) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            key = str(raw_key)
            key_lower = key.lower()
            if key_lower in policy.sensitive_field_names and key_lower not in policy.safe_field_names:
                redacted[key] = policy.mask
                continue
            redacted[key] = _redact(raw_val, path=path + (key_lower,), policy=policy)
        return redacted

    if isinstance(value, list):
        return [_redact(item, path=path + ("[]",), policy=policy) for item in value]

    if isinstance(value, tuple):
        return [_redact(item, path=path + ("[]",), policy=policy) for item in value]

    if isinstance(value, str):
        if path and path[-1] in policy.safe_field_names:
            return value
        return _redact_string(value, policy)

    return value


def _redact_string(value: str, policy: RedactionPolicy) -> str:
    redacted = value
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(policy.mask, redacted)
    return redacted
