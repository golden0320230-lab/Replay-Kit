"""CI guard: passive artifact replay must succeed with outbound sockets blocked."""

from __future__ import annotations

from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from replaypack.artifact import read_artifact
from replaypack.replay import ReplayConfig, write_replay_stub_artifact


def main() -> int:
    source = Path("runs/passive/listener-capture.rpk")
    if not source.exists():
        raise SystemExit(
            "missing passive listener capture artifact: runs/passive/listener-capture.rpk"
        )

    out_path = Path("runs/passive/listener-replay-network-off.rpk")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run = read_artifact(source)

    original_create_connection = socket.create_connection

    def _blocked_create_connection(*_args, **_kwargs):
        raise OSError("network disabled by passive listener replay guard")

    socket.create_connection = _blocked_create_connection
    try:
        write_replay_stub_artifact(
            run,
            str(out_path),
            config=ReplayConfig(seed=19, fixed_clock="2026-02-23T00:00:00Z"),
        )
    finally:
        socket.create_connection = original_create_connection

    print(f"network-off passive replay guard wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
