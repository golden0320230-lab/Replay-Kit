"""Runtime plugin manager with fault-isolated hook dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
import warnings

from replaypack.plugins.base import (
    CaptureEndEvent,
    CaptureStartEvent,
    CaptureStepEvent,
    DiffEndEvent,
    DiffStartEvent,
    ReplayEndEvent,
    ReplayStartEvent,
)


@dataclass(frozen=True, slots=True)
class PluginDiagnostic:
    plugin_name: str
    hook: str
    error_type: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "plugin_name": self.plugin_name,
            "hook": self.hook,
            "error_type": self.error_type,
            "message": self.message,
        }


@dataclass(slots=True)
class PluginManager:
    """Executes lifecycle plugin hooks and captures plugin failures."""

    plugins: tuple[object, ...] = ()
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)

    def clear_diagnostics(self) -> None:
        self.diagnostics.clear()

    def on_capture_start(self, event: CaptureStartEvent) -> None:
        self._dispatch("on_capture_start", event)

    def on_capture_step(self, event: CaptureStepEvent) -> None:
        self._dispatch("on_capture_step", event)

    def on_capture_end(self, event: CaptureEndEvent) -> None:
        self._dispatch("on_capture_end", event)

    def on_replay_start(self, event: ReplayStartEvent) -> None:
        self._dispatch("on_replay_start", event)

    def on_replay_end(self, event: ReplayEndEvent) -> None:
        self._dispatch("on_replay_end", event)

    def on_diff_start(self, event: DiffStartEvent) -> None:
        self._dispatch("on_diff_start", event)

    def on_diff_end(self, event: DiffEndEvent) -> None:
        self._dispatch("on_diff_end", event)

    def _dispatch(self, hook: str, event: object) -> None:
        for plugin in self.plugins:
            callback = getattr(plugin, hook, None)
            if callback is None:
                continue
            try:
                callback(event)
            except Exception as error:  # pragma: no cover - defensive isolation
                diagnostic = PluginDiagnostic(
                    plugin_name=_plugin_name(plugin),
                    hook=hook,
                    error_type=error.__class__.__name__,
                    message=str(error),
                )
                self.diagnostics.append(diagnostic)
                warnings.warn(
                    (
                        f"ReplayPack plugin failure: plugin={diagnostic.plugin_name} "
                        f"hook={diagnostic.hook} "
                        f"error={diagnostic.error_type}: {diagnostic.message}"
                    ),
                    RuntimeWarning,
                    stacklevel=2,
                )


def _plugin_name(plugin: object) -> str:
    name = getattr(plugin, "name", plugin.__class__.__name__)
    return str(name)
