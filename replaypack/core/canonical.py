"""Deterministic canonicalization helpers for ReplayKit."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import posixpath
import re
from typing import Any

UNORDERED_LIST_FIELD_NAMES = frozenset({"tags", "labels", "capabilities"})

VOLATILE_FIELD_NAMES = frozenset(
    {
        "duration_ms",
        "latency_ms",
        "wall_time_ms",
        "request_id",
        "trace_id",
        "span_id",
        "captured_at",
        "captured_ns",
        "thread_id",
        "pid",
    }
)

PATH_FIELD_HINTS = frozenset(
    {
        "path",
        "file",
        "filepath",
        "file_path",
        "cwd",
        "dir",
        "directory",
        "working_directory",
    }
)

TIMESTAMP_FIELD_HINTS = frozenset(
    {
        "timestamp",
        "created_at",
        "updated_at",
        "started_at",
        "ended_at",
        "captured_at",
    }
)

_WINDOWS_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")


def canonicalize(
    value: Any,
    *,
    strip_volatile: bool = False,
    volatile_field_names: frozenset[str] = VOLATILE_FIELD_NAMES,
    unordered_list_field_names: frozenset[str] = UNORDERED_LIST_FIELD_NAMES,
) -> Any:
    """Normalize values to a deterministic representation."""
    return _canonicalize(
        value,
        path=(),
        strip_volatile=strip_volatile,
        volatile_field_names=volatile_field_names,
        unordered_list_field_names=unordered_list_field_names,
    )


def canonical_json(
    value: Any,
    *,
    strip_volatile: bool = False,
    volatile_field_names: frozenset[str] = VOLATILE_FIELD_NAMES,
    unordered_list_field_names: frozenset[str] = UNORDERED_LIST_FIELD_NAMES,
) -> str:
    """Serialize a value to stable canonical JSON."""
    canonical_value = canonicalize(
        value,
        strip_volatile=strip_volatile,
        volatile_field_names=volatile_field_names,
        unordered_list_field_names=unordered_list_field_names,
    )
    return json.dumps(
        canonical_value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonicalize(
    value: Any,
    *,
    path: tuple[str, ...],
    strip_volatile: bool,
    volatile_field_names: frozenset[str],
    unordered_list_field_names: frozenset[str],
) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda raw: str(raw)):
            key_name = str(key)
            if strip_volatile and key_name.lower() in volatile_field_names:
                continue
            normalized[key_name] = _canonicalize(
                value[key],
                path=path + (key_name,),
                strip_volatile=strip_volatile,
                volatile_field_names=volatile_field_names,
                unordered_list_field_names=unordered_list_field_names,
            )
        return normalized

    if isinstance(value, (list, tuple)):
        normalized_list = [
            _canonicalize(
                item,
                path=path + ("[]",),
                strip_volatile=strip_volatile,
                volatile_field_names=volatile_field_names,
                unordered_list_field_names=unordered_list_field_names,
            )
            for item in value
        ]
        if path and path[-1].lower() in unordered_list_field_names:
            normalized_list.sort(key=_stable_item_sort_key)
        return normalized_list

    if isinstance(value, str):
        return _normalize_string(value, path)

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and infinity are not supported in canonical JSON")
        return float(f"{value:.12g}")

    return value


def _stable_item_sort_key(item: Any) -> str:
    return json.dumps(item, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _normalize_string(value: str, path: tuple[str, ...]) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if path:
        key = path[-1].lower()
        if _is_path_field(key):
            return _normalize_path(text)
        if key in TIMESTAMP_FIELD_HINTS:
            return _normalize_timestamp(text)
    return text


def _is_path_field(key: str) -> bool:
    return key in PATH_FIELD_HINTS or key.endswith("_path") or key.endswith("_dir")


def _normalize_path(path_value: str) -> str:
    candidate = path_value.replace("\\", "/")
    match = _WINDOWS_DRIVE_RE.match(candidate)
    if match:
        drive = match.group("drive").lower()
        rest = match.group("rest")
        candidate = f"/{drive}/{rest}"

    candidate = re.sub(r"/{2,}", "/", candidate)
    normalized = posixpath.normpath(candidate)

    if candidate.endswith("/") and normalized != "/":
        normalized = f"{normalized}/"

    return normalized


def _normalize_timestamp(timestamp_value: str) -> str:
    raw = timestamp_value.strip()
    if not raw:
        return raw

    parse_target = raw[:-1] + "+00:00" if raw.endswith("Z") else raw

    try:
        parsed = datetime.fromisoformat(parse_target)
    except ValueError:
        return raw

    if parsed.tzinfo is None:
        return raw

    as_utc = parsed.astimezone(timezone.utc)
    return as_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
