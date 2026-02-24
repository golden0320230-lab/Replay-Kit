"""macOS transparent interception controller (MVP-safe scaffolding)."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Any, Callable

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class _PlanStep:
    step_id: str
    description: str
    apply: tuple[str, ...]
    rollback: tuple[str, ...]
    required: bool = True


class TransparentControllerError(RuntimeError):
    """Raised when required transparent intercept operations fail."""

    def __init__(self, message: str, *, failures: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.failures = failures


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )


def _build_macos_plan(*, listener_host: str, listener_port: int) -> list[_PlanStep]:
    listener_endpoint = f"{listener_host}:{listener_port}"
    return [
        _PlanStep(
            step_id="pf.enable",
            description=f"enable pf to allow transparent redirect to {listener_endpoint}",
            apply=("pfctl", "-E"),
            rollback=("pfctl", "-d"),
            required=True,
        ),
        _PlanStep(
            step_id="networksetup.preflight",
            description="preflight network service inventory before redirect rules",
            apply=("networksetup", "-listallnetworkservices"),
            rollback=("networksetup", "-listallnetworkservices"),
            required=False,
        ),
    ]


def _normalize_rollback_handles(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        if not isinstance(command, list) or not all(
            isinstance(token, str) and token for token in command
        ):
            continue
        step_id = item.get("step_id")
        normalized.append(
            {
                "step_id": str(step_id) if isinstance(step_id, str) and step_id else f"handle-{index}",
                "command": list(command),
            }
        )
    return normalized


class TransparentMacOSController:
    """Apply and revert transparent interception rules for macOS."""

    def __init__(
        self,
        *,
        execute: bool,
        runner: CommandRunner | None = None,
    ) -> None:
        self.execute = bool(execute)
        self.runner: CommandRunner = runner or _default_runner

    def apply(
        self,
        *,
        listener_host: str,
        listener_port: int,
    ) -> dict[str, Any]:
        plan = _build_macos_plan(
            listener_host=listener_host,
            listener_port=listener_port,
        )
        operations: list[dict[str, Any]] = []
        rollback_handles: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for step in plan:
            operation: dict[str, Any] = {
                "step_id": step.step_id,
                "description": step.description,
                "required": step.required,
                "apply": list(step.apply),
                "rollback": list(step.rollback),
                "executed": self.execute,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            }
            if self.execute:
                completed = self.runner(list(step.apply))
                operation["returncode"] = int(completed.returncode)
                operation["stdout"] = completed.stdout or ""
                operation["stderr"] = completed.stderr or ""
            operations.append(operation)
            rollback_handles.append(
                {
                    "step_id": step.step_id,
                    "command": list(step.rollback),
                }
            )
            if operation["returncode"] != 0 and step.required:
                failures.append(
                    {
                        "step_id": step.step_id,
                        "apply": list(step.apply),
                        "returncode": operation["returncode"],
                        "stderr": operation["stderr"],
                    }
                )

        if failures:
            raise TransparentControllerError(
                "transparent intercept apply failed for required operation(s).",
                failures=failures,
            )

        return {
            "executed": self.execute,
            "listener_host": listener_host,
            "listener_port": listener_port,
            "operation_count": len(operations),
            "operations": operations,
            "rollback_handles": rollback_handles,
        }

    def rollback(self, rollback_handles: Any) -> dict[str, Any]:
        normalized_handles = _normalize_rollback_handles(rollback_handles)
        attempted = 0
        failures: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = []

        for handle in reversed(normalized_handles):
            attempted += 1
            command = list(handle["command"])
            operation: dict[str, Any] = {
                "step_id": handle["step_id"],
                "command": command,
                "executed": self.execute,
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            }
            if self.execute:
                completed = self.runner(command)
                operation["returncode"] = int(completed.returncode)
                operation["stdout"] = completed.stdout or ""
                operation["stderr"] = completed.stderr or ""
            operations.append(operation)
            if operation["returncode"] != 0:
                failures.append(
                    {
                        "step_id": handle["step_id"],
                        "command": command,
                        "returncode": operation["returncode"],
                        "stderr": operation["stderr"],
                    }
                )

        return {
            "executed": self.execute,
            "attempted": attempted,
            "ok": len(failures) == 0,
            "failures": failures,
            "operations": operations,
        }
