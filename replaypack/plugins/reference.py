"""Reference lifecycle plugin implementation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from replaypack.plugins.base import (
    CaptureEndEvent,
    CaptureStartEvent,
    CaptureStepEvent,
    DiffEndEvent,
    DiffStartEvent,
    LifecyclePlugin,
    ReplayEndEvent,
    ReplayStartEvent,
)


@dataclass(slots=True)
class LifecycleTracePlugin(LifecyclePlugin):
    """Reference plugin that writes lifecycle hooks to NDJSON."""

    output_path: str = "runs/plugins/lifecycle-trace.ndjson"
    name: str = "lifecycle-trace"

    def on_capture_start(self, event: CaptureStartEvent) -> None:
        self._append("on_capture_start", event)

    def on_capture_step(self, event: CaptureStepEvent) -> None:
        self._append("on_capture_step", event)

    def on_capture_end(self, event: CaptureEndEvent) -> None:
        self._append("on_capture_end", event)

    def on_replay_start(self, event: ReplayStartEvent) -> None:
        self._append("on_replay_start", event)

    def on_replay_end(self, event: ReplayEndEvent) -> None:
        self._append("on_replay_end", event)

    def on_diff_start(self, event: DiffStartEvent) -> None:
        self._append("on_diff_start", event)

    def on_diff_end(self, event: DiffEndEvent) -> None:
        self._append("on_diff_end", event)

    def _append(self, hook: str, event: object) -> None:
        path = Path(self.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "hook": hook,
            "plugin": self.name,
            "event": asdict(event),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
