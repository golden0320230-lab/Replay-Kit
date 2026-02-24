import subprocess

import pytest

from replaypack.transparent_macos import (
    TransparentControllerError,
    TransparentMacOSController,
)


def test_transparent_controller_apply_dry_run_skips_runner_calls() -> None:
    calls: list[list[str]] = []

    def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = TransparentMacOSController(execute=False, runner=_runner)
    result = controller.apply(listener_host="127.0.0.1", listener_port=63797)

    assert calls == []
    assert result["executed"] is False
    assert result["operation_count"] >= 1
    assert len(result["rollback_handles"]) == result["operation_count"]


def test_transparent_controller_apply_execute_failure_raises() -> None:
    def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv and argv[0] == "pfctl":
            return subprocess.CompletedProcess(argv, 1, "", "permission denied")
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = TransparentMacOSController(execute=True, runner=_runner)

    with pytest.raises(TransparentControllerError) as error:
        controller.apply(listener_host="127.0.0.1", listener_port=60000)

    assert error.value.failures
    assert error.value.failures[0]["step_id"] == "pf.enable"


def test_transparent_controller_rollback_execute_runs_reverse_order() -> None:
    calls: list[list[str]] = []

    def _runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    controller = TransparentMacOSController(execute=True, runner=_runner)
    rollback_result = controller.rollback(
        [
            {"step_id": "first", "command": ["cmd", "first"]},
            {"step_id": "second", "command": ["cmd", "second"]},
        ]
    )

    assert rollback_result["ok"] is True
    assert rollback_result["attempted"] == 2
    assert calls == [["cmd", "second"], ["cmd", "first"]]


def test_transparent_controller_rollback_ignores_invalid_handles() -> None:
    controller = TransparentMacOSController(execute=False)
    rollback_result = controller.rollback([{"step_id": "invalid", "command": [""]}, "bad"])

    assert rollback_result["ok"] is True
    assert rollback_result["attempted"] == 0
