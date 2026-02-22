"""Determinism guardrails for replay/assert workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from replaypack.core.models import Run
from replaypack.diff.models import RunDiffResult

GuardrailMode = Literal["off", "warn", "fail"]
NondeterminismKind = Literal["random_unseeded", "time_unstable"]

_ALLOWED_MODES: frozenset[str] = frozenset({"off", "warn", "fail"})

_RANDOM_USAGE_KEYS: frozenset[str] = frozenset(
    {
        "uses_random",
        "random_used",
        "random_usage",
        "random_enabled",
    }
)
_RANDOM_SEED_KEYS: frozenset[str] = frozenset(
    {
        "seed",
        "random_seed",
        "rng_seed",
        "replay_seed",
    }
)

_TIME_USAGE_KEYS: frozenset[str] = frozenset(
    {
        "uses_time",
        "time_used",
        "time_usage",
        "clock_used",
        "uses_datetime_now",
        "uses_time_now",
    }
)
_TIME_FIXED_KEYS: frozenset[str] = frozenset(
    {
        "fixed_clock",
        "clock_fixed",
        "time_fixed",
        "replay_fixed_clock",
    }
)

_RANDOM_VOLATILE_TOKENS: frozenset[str] = frozenset(
    {
        "request_id",
        "trace_id",
        "span_id",
        "nonce",
        "uuid",
        "random",
        "rand",
    }
)
_TIME_VOLATILE_TOKENS: frozenset[str] = frozenset(
    {
        "timestamp",
        "created_at",
        "updated_at",
        "started_at",
        "ended_at",
        "time",
        "clock",
    }
)


@dataclass(slots=True, frozen=True)
class NondeterminismFinding:
    """Single nondeterminism indicator."""

    kind: NondeterminismKind
    path: str
    message: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": self.path,
            "message": self.message,
            "source": self.source,
        }


def normalize_guardrail_mode(value: str) -> GuardrailMode:
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_MODES:
        raise ValueError(
            f"Invalid nondeterminism mode '{value}'. "
            "Supported modes: off, warn, fail"
        )
    return normalized  # type: ignore[return-value]


def detect_run_nondeterminism(
    run: Run,
    *,
    run_label: str,
) -> list[NondeterminismFinding]:
    """Inspect a run for deterministic guardrail indicators."""
    findings: list[NondeterminismFinding] = []
    seen: set[tuple[NondeterminismKind, str, str]] = set()

    random_usage_paths: list[str] = []
    random_seed_paths: list[str] = []
    time_usage_paths: list[str] = []
    time_fixed_paths: list[str] = []

    for path, key, value in _iter_key_values(run.environment_fingerprint, "/environment_fingerprint"):
        _collect_key_observations(
            key=key,
            value=value,
            path=path,
            random_usage_paths=random_usage_paths,
            random_seed_paths=random_seed_paths,
            time_usage_paths=time_usage_paths,
            time_fixed_paths=time_fixed_paths,
        )

    for path, key, value in _iter_key_values(run.runtime_versions, "/runtime_versions"):
        _collect_key_observations(
            key=key,
            value=value,
            path=path,
            random_usage_paths=random_usage_paths,
            random_seed_paths=random_seed_paths,
            time_usage_paths=time_usage_paths,
            time_fixed_paths=time_fixed_paths,
        )

    for step_index, step in enumerate(run.steps, start=1):
        base = f"/steps/{step_index}"
        for path, key, value in _iter_key_values(step.input, f"{base}/input"):
            _collect_key_observations(
                key=key,
                value=value,
                path=path,
                random_usage_paths=random_usage_paths,
                random_seed_paths=random_seed_paths,
                time_usage_paths=time_usage_paths,
                time_fixed_paths=time_fixed_paths,
            )
        for path, key, value in _iter_key_values(step.output, f"{base}/output"):
            _collect_key_observations(
                key=key,
                value=value,
                path=path,
                random_usage_paths=random_usage_paths,
                random_seed_paths=random_seed_paths,
                time_usage_paths=time_usage_paths,
                time_fixed_paths=time_fixed_paths,
            )
        for path, key, value in _iter_key_values(step.metadata, f"{base}/metadata"):
            _collect_key_observations(
                key=key,
                value=value,
                path=path,
                random_usage_paths=random_usage_paths,
                random_seed_paths=random_seed_paths,
                time_usage_paths=time_usage_paths,
                time_fixed_paths=time_fixed_paths,
            )

    if random_usage_paths and not random_seed_paths:
        first = random_usage_paths[0]
        _append_finding(
            findings,
            seen,
            NondeterminismFinding(
                kind="random_unseeded",
                source=run_label,
                path=first,
                message=(
                    "Randomness usage detected without a stable seed marker "
                    "(expected one of: seed/random_seed/rng_seed/replay_seed)."
                ),
            ),
        )

    if time_usage_paths and not time_fixed_paths:
        first = time_usage_paths[0]
        _append_finding(
            findings,
            seen,
            NondeterminismFinding(
                kind="time_unstable",
                source=run_label,
                path=first,
                message=(
                    "Time usage detected without a fixed clock marker "
                    "(expected one of: fixed_clock/time_fixed/replay_fixed_clock)."
                ),
            ),
        )

    return findings


def detect_diff_nondeterminism(
    diff: RunDiffResult,
    *,
    source: str = "diff",
) -> list[NondeterminismFinding]:
    """Inspect diff changes for volatile random/time indicators."""
    findings: list[NondeterminismFinding] = []
    seen: set[tuple[NondeterminismKind, str, str]] = set()

    for step in diff.step_diffs:
        if step.status == "identical":
            continue
        for change in step.changes:
            token_set = _tokens_for_path(change.path)
            if token_set & _RANDOM_VOLATILE_TOKENS:
                _append_finding(
                    findings,
                    seen,
                    NondeterminismFinding(
                        kind="random_unseeded",
                        source=source,
                        path=f"/steps/{step.index}{change.path}",
                        message=(
                            "Diff changed a random-volatile field "
                            f"({', '.join(sorted(token_set & _RANDOM_VOLATILE_TOKENS))})."
                        ),
                    ),
                )
            if token_set & _TIME_VOLATILE_TOKENS:
                _append_finding(
                    findings,
                    seen,
                    NondeterminismFinding(
                        kind="time_unstable",
                        source=source,
                        path=f"/steps/{step.index}{change.path}",
                        message=(
                            "Diff changed a time-volatile field "
                            f"({', '.join(sorted(token_set & _TIME_VOLATILE_TOKENS))})."
                        ),
                    ),
                )

    return findings


def guardrail_payload(
    *,
    mode: GuardrailMode,
    findings: list[NondeterminismFinding],
) -> dict[str, Any]:
    status: str
    if mode == "off":
        status = "off"
    elif not findings:
        status = "clear"
    elif mode == "warn":
        status = "warn"
    else:
        status = "fail"

    return {
        "mode": mode,
        "status": status,
        "count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }


def render_guardrail_summary(
    *,
    mode: GuardrailMode,
    findings: list[NondeterminismFinding],
) -> str:
    if mode == "off":
        return ""

    if not findings:
        return "nondeterminism guardrails: clear"

    lines = [
        f"nondeterminism guardrails: {len(findings)} indicator(s) detected (mode={mode})"
    ]
    for finding in findings:
        lines.append(
            f"- [{finding.kind}] {finding.path} ({finding.source}) {finding.message}"
        )
    return "\n".join(lines)


def _iter_key_values(value: Any, path: str) -> list[tuple[str, str, Any]]:
    rows: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_name = str(key)
            child_path = f"{path}/{_escape_pointer(key_name)}"
            rows.append((child_path, key_name, child))
            rows.extend(_iter_key_values(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}/{idx}"
            rows.extend(_iter_key_values(child, child_path))
    return rows


def _collect_key_observations(
    *,
    key: str,
    value: Any,
    path: str,
    random_usage_paths: list[str],
    random_seed_paths: list[str],
    time_usage_paths: list[str],
    time_fixed_paths: list[str],
) -> None:
    lowered = key.lower()
    if lowered in _RANDOM_USAGE_KEYS and _truthy(value):
        random_usage_paths.append(path)
    if lowered in _RANDOM_SEED_KEYS and _has_stable_value(value):
        random_seed_paths.append(path)
    if lowered in _TIME_USAGE_KEYS and _truthy(value):
        time_usage_paths.append(path)
    if lowered in _TIME_FIXED_KEYS and _has_stable_value(value):
        time_fixed_paths.append(path)


def _has_stable_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _tokens_for_path(path: str) -> set[str]:
    tokens = set()
    for token in path.split("/"):
        normalized = token.strip().lower()
        if normalized:
            tokens.add(normalized)
    return tokens


def _append_finding(
    findings: list[NondeterminismFinding],
    seen: set[tuple[NondeterminismKind, str, str]],
    finding: NondeterminismFinding,
) -> None:
    key = (finding.kind, finding.source, finding.path)
    if key in seen:
        return
    seen.add(key)
    findings.append(finding)


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
