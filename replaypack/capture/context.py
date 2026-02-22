"""Run-scoped capture context and event recording."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import platform
import threading
from typing import Any, Iterator

from replaypack.capture.policy import InterceptionPolicy
from replaypack.capture.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy, redact_payload
from replaypack.core.models import Run, Step
from replaypack.plugins import (
    CaptureEndEvent,
    CaptureStartEvent,
    CaptureStepEvent,
    PluginManager,
    get_active_plugin_manager,
)

_CURRENT_CONTEXT: ContextVar["CaptureContext | None"] = ContextVar(
    "replaypack_current_capture_context", default=None
)


@dataclass(slots=True)
class CaptureContext:
    """Mutable state for a single recorded run."""

    run_id: str
    timestamp: str
    environment_fingerprint: dict[str, Any]
    runtime_versions: dict[str, Any]
    policy: InterceptionPolicy = field(default_factory=InterceptionPolicy)
    redaction_policy: RedactionPolicy = field(default_factory=lambda: DEFAULT_REDACTION_POLICY)
    plugin_manager: PluginManager = field(default_factory=get_active_plugin_manager)
    steps: list[Step] = field(default_factory=list)
    _counter: int = 0
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        timestamp: str | None = None,
        environment_fingerprint: dict[str, Any] | None = None,
        runtime_versions: dict[str, Any] | None = None,
        policy: InterceptionPolicy | None = None,
        redaction_policy: RedactionPolicy | None = None,
        plugin_manager: PluginManager | None = None,
    ) -> "CaptureContext":
        return cls(
            run_id=run_id,
            timestamp=timestamp or _utcnow_iso(),
            environment_fingerprint=environment_fingerprint or _default_environment_fingerprint(),
            runtime_versions=runtime_versions or _default_runtime_versions(),
            policy=policy or InterceptionPolicy(),
            redaction_policy=redaction_policy or DEFAULT_REDACTION_POLICY,
            plugin_manager=plugin_manager or get_active_plugin_manager(),
        )

    def record_step(
        self,
        step_type: str,
        *,
        input_payload: Any,
        output_payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> Step:
        with self._lock:
            self._counter += 1
            step = Step(
                id=f"step-{self._counter:06d}",
                type=step_type,
                input=redact_payload(input_payload, policy=self.redaction_policy),
                output=redact_payload(output_payload, policy=self.redaction_policy),
                metadata=redact_payload(metadata or {}, policy=self.redaction_policy),
            ).with_hash()
            self.steps.append(step)
            self.plugin_manager.on_capture_step(
                CaptureStepEvent(
                    run_id=self.run_id,
                    step_id=step.id,
                    step_type=step.type,
                    metadata=dict(step.metadata),
                )
            )
            return step

    def to_run(self) -> Run:
        with self._lock:
            return Run(
                id=self.run_id,
                timestamp=self.timestamp,
                environment_fingerprint=dict(self.environment_fingerprint),
                runtime_versions=dict(self.runtime_versions),
                steps=list(self.steps),
            )


def get_current_context() -> CaptureContext | None:
    return _CURRENT_CONTEXT.get()


@contextmanager
def capture_run(
    *,
    run_id: str,
    timestamp: str | None = None,
    environment_fingerprint: dict[str, Any] | None = None,
    runtime_versions: dict[str, Any] | None = None,
    policy: InterceptionPolicy | None = None,
    redaction_policy: RedactionPolicy | None = None,
    plugin_manager: PluginManager | None = None,
) -> Iterator[CaptureContext]:
    # Nested capture scopes are supported with stack semantics: the inner scope
    # becomes current for its duration, then the previous context is restored.
    context = CaptureContext.create(
        run_id=run_id,
        timestamp=timestamp,
        environment_fingerprint=environment_fingerprint,
        runtime_versions=runtime_versions,
        policy=policy,
        redaction_policy=redaction_policy,
        plugin_manager=plugin_manager,
    )
    token = _CURRENT_CONTEXT.set(context)
    context.plugin_manager.on_capture_start(
        CaptureStartEvent(run_id=context.run_id, timestamp=context.timestamp)
    )
    status = "ok"
    error_type: str | None = None
    error_message: str | None = None
    try:
        yield context
    except Exception as error:
        status = "error"
        error_type = error.__class__.__name__
        error_message = str(error)
        raise
    finally:
        context.plugin_manager.on_capture_end(
            CaptureEndEvent(
                run_id=context.run_id,
                step_count=len(context.steps),
                status=status,
                error_type=error_type,
                error_message=error_message,
            )
        )
        _CURRENT_CONTEXT.reset(token)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _default_environment_fingerprint() -> dict[str, str]:
    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "cwd": os.getcwd(),
    }


def _default_runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "replaykit": "0.1.0",
    }
