"""Security-first redaction policy for capture payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Mapping

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
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"(?i)\b[a-z0-9._-]{3,}token(?:[a-z0-9._-]{3,})?\b"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
)


class RedactionPolicyConfigError(ValueError):
    """Raised when a redaction policy config payload is invalid."""


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Redaction policy for masking sensitive fields and values."""

    version: str = "1.0"
    enabled: bool = True
    mask: str = "[REDACTED]"
    sensitive_field_names: frozenset[str] = field(default_factory=lambda: SENSITIVE_FIELD_NAMES)
    safe_field_names: frozenset[str] = field(default_factory=lambda: SAFE_FIELD_NAMES)
    secret_value_patterns: tuple[re.Pattern[str], ...] = field(
        default_factory=lambda: SECRET_VALUE_PATTERNS
    )
    sensitive_path_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)


DEFAULT_REDACTION_POLICY = RedactionPolicy()


def build_redaction_policy(
    *,
    version: str = "1.0-custom",
    enabled: bool = True,
    mask: str = "[REDACTED]",
    base_policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
    extra_sensitive_field_names: tuple[str, ...] = (),
    extra_safe_field_names: tuple[str, ...] = (),
    extra_secret_value_patterns: tuple[str, ...] = (),
    extra_sensitive_path_patterns: tuple[str, ...] = (),
) -> RedactionPolicy:
    """Build a custom redaction policy by extending a secure base policy."""
    if not version.strip():
        raise RedactionPolicyConfigError("Redaction policy version cannot be empty.")
    if not mask:
        raise RedactionPolicyConfigError("Redaction mask cannot be empty.")

    sensitive = set(base_policy.sensitive_field_names)
    sensitive.update(_normalize_field_names(extra_sensitive_field_names, key="extra_sensitive_field_names"))

    safe = set(base_policy.safe_field_names)
    safe.update(_normalize_field_names(extra_safe_field_names, key="extra_safe_field_names"))
    # Security-first invariant: a sensitive key must never become safe.
    safe.difference_update(sensitive)

    secret_patterns = tuple(base_policy.secret_value_patterns) + _compile_patterns(
        extra_secret_value_patterns,
        key="extra_secret_value_patterns",
    )
    path_patterns = tuple(base_policy.sensitive_path_patterns) + _compile_patterns(
        extra_sensitive_path_patterns,
        key="extra_sensitive_path_patterns",
    )

    return RedactionPolicy(
        version=version.strip(),
        enabled=enabled,
        mask=mask,
        sensitive_field_names=frozenset(sensitive),
        safe_field_names=frozenset(safe),
        secret_value_patterns=secret_patterns,
        sensitive_path_patterns=path_patterns,
    )


def redaction_policy_from_config(
    config: Mapping[str, Any],
    *,
    base_policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
) -> RedactionPolicy:
    """Create a redaction policy from config mapping."""
    supported_keys = {
        "version",
        "enabled",
        "mask",
        "extra_sensitive_field_names",
        "extra_safe_field_names",
        "extra_secret_value_patterns",
        "extra_sensitive_path_patterns",
    }
    unknown = sorted(set(config.keys()) - supported_keys)
    if unknown:
        raise RedactionPolicyConfigError(
            "Unsupported redaction config keys: " + ", ".join(unknown)
        )

    version = config.get("version")
    if version is None:
        version = f"{base_policy.version}+custom"
    elif not isinstance(version, str):
        raise RedactionPolicyConfigError("redaction config key 'version' must be a string.")

    enabled_value = config.get("enabled", base_policy.enabled)
    if not isinstance(enabled_value, bool):
        raise RedactionPolicyConfigError("redaction config key 'enabled' must be a boolean.")

    mask_value = config.get("mask", base_policy.mask)
    if not isinstance(mask_value, str):
        raise RedactionPolicyConfigError("redaction config key 'mask' must be a string.")

    return build_redaction_policy(
        version=version,
        enabled=enabled_value,
        mask=mask_value,
        base_policy=base_policy,
        extra_sensitive_field_names=_read_string_list(
            config,
            key="extra_sensitive_field_names",
        ),
        extra_safe_field_names=_read_string_list(
            config,
            key="extra_safe_field_names",
        ),
        extra_secret_value_patterns=_read_string_list(
            config,
            key="extra_secret_value_patterns",
        ),
        extra_sensitive_path_patterns=_read_string_list(
            config,
            key="extra_sensitive_path_patterns",
        ),
    )


def load_redaction_policy_from_file(
    path: str | Path,
    *,
    base_policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
) -> RedactionPolicy:
    """Load redaction policy config from JSON file."""
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as error:
        raise RedactionPolicyConfigError(
            f"Invalid redaction config JSON ({config_path}): {error}"
        ) from error

    if not isinstance(raw, dict):
        raise RedactionPolicyConfigError(
            f"Redaction config must be a JSON object ({config_path})."
        )

    return redaction_policy_from_config(raw, base_policy=base_policy)


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
            child_path = path + (key_lower,)
            if key_lower in policy.sensitive_field_names or _matches_sensitive_path(
                child_path,
                policy=policy,
            ):
                redacted[key] = policy.mask
                continue
            redacted[key] = _redact(raw_val, path=child_path, policy=policy)
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
    for pattern in policy.secret_value_patterns:
        redacted = pattern.sub(policy.mask, redacted)
    return redacted


def _matches_sensitive_path(path: tuple[str, ...], *, policy: RedactionPolicy) -> bool:
    if not policy.sensitive_path_patterns:
        return False
    path_value = "/" + "/".join(path)
    return any(pattern.search(path_value) for pattern in policy.sensitive_path_patterns)


def _compile_patterns(
    patterns: tuple[str, ...],
    *,
    key: str,
) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise RedactionPolicyConfigError(
                f"redaction config key '{key}' must contain strings."
            )
        try:
            compiled.append(re.compile(pattern))
        except re.error as error:
            raise RedactionPolicyConfigError(
                f"Invalid regex in '{key}': {pattern!r} ({error})"
            ) from error
    return tuple(compiled)


def _normalize_field_names(values: tuple[str, ...], *, key: str) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise RedactionPolicyConfigError(
                f"redaction config key '{key}' must contain strings."
            )
        lowered = value.strip().lower()
        if lowered:
            normalized.add(lowered)
    return normalized


def _read_string_list(config: Mapping[str, Any], *, key: str) -> tuple[str, ...]:
    if key not in config:
        return ()
    value = config[key]
    if not isinstance(value, list):
        raise RedactionPolicyConfigError(
            f"redaction config key '{key}' must be a JSON array of strings."
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RedactionPolicyConfigError(
                f"redaction config key '{key}' must be a JSON array of strings."
            )
        if item.strip():
            result.append(item.strip())
    return tuple(result)
