"""Persistent state helpers for passive listener daemon lifecycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_listener_state_path() -> Path:
    return Path("runs/listener/state.json")


def load_listener_state(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def write_listener_state(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def remove_listener_state(path: str | Path) -> None:
    target = Path(path)
    try:
        target.unlink()
    except FileNotFoundError:
        return


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    wnohang = getattr(os, "WNOHANG", None)
    if hasattr(os, "waitpid") and wnohang is not None:
        try:
            waited_pid, _status = os.waitpid(pid, wnohang)
        except ChildProcessError:
            waited_pid = 0
        if waited_pid == pid:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
