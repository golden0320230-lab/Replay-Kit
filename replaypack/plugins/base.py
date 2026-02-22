"""Versioned plugin interfaces and lifecycle event payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

PLUGIN_API_VERSION = "1.0"
PLUGIN_CONFIG_VERSION = 1
PLUGIN_CONFIG_ENV_VAR = "REPLAYKIT_PLUGIN_CONFIG"

LifecycleStatus = Literal["ok", "error"]


@dataclass(frozen=True, slots=True)
class CaptureStartEvent:
    run_id: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureStepEvent:
    run_id: str
    step_id: str
    step_type: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureEndEvent:
    run_id: str
    step_count: int
    status: LifecycleStatus
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReplayStartEvent:
    mode: str
    source_run_id: str
    rerun_from_run_id: str | None
    seed: int
    fixed_clock: str
    source_step_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReplayEndEvent:
    mode: str
    source_run_id: str
    rerun_from_run_id: str | None
    status: LifecycleStatus
    replay_run_id: str | None = None
    step_count: int | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiffStartEvent:
    left_run_id: str
    right_run_id: str
    stop_at_first_divergence: bool
    max_changes_per_step: int
    total_left_steps: int
    total_right_steps: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DiffEndEvent:
    left_run_id: str
    right_run_id: str
    status: LifecycleStatus
    identical: bool | None = None
    first_divergence_index: int | None = None
    summary: dict[str, int] | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LifecyclePlugin:
    """Base no-op lifecycle plugin interface (API v1.x)."""

    api_version = PLUGIN_API_VERSION
    name = "lifecycle-plugin"

    def on_capture_start(self, event: CaptureStartEvent) -> None:
        return None

    def on_capture_step(self, event: CaptureStepEvent) -> None:
        return None

    def on_capture_end(self, event: CaptureEndEvent) -> None:
        return None

    def on_replay_start(self, event: ReplayStartEvent) -> None:
        return None

    def on_replay_end(self, event: ReplayEndEvent) -> None:
        return None

    def on_diff_start(self, event: DiffStartEvent) -> None:
        return None

    def on_diff_end(self, event: DiffEndEvent) -> None:
        return None
