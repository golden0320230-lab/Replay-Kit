"""Cross-platform passive-listener golden-path smoke for CI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import requests


def _run_cli(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "replaypack", *args]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    out_dir = Path("runs/passive")
    out_dir.mkdir(parents=True, exist_ok=True)
    state_file = out_dir / "listener-state.json"
    artifact_path = out_dir / "listener-capture.rpk"

    started: dict[str, Any] | None = None
    try:
        start = _run_cli(
            [
                "listen",
                "start",
                "--state-file",
                str(state_file),
                "--out",
                str(artifact_path),
                "--json",
            ]
        )
        started = json.loads(start.stdout.strip())
        _write_json(out_dir / "listener-start.json", started)
        base_url = f"http://{started['host']}:{started['port']}"

        openai = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
            timeout=2.0,
        )
        openai.raise_for_status()
        _write_json(out_dir / "listener-openai-response.json", openai.json())

        codex = requests.post(
            f"{base_url}/agent/codex/events",
            json={
                "events": [
                    {
                        "type": "model.request",
                        "input": {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]},
                    },
                    {
                        "type": "model.response",
                        "request_id": "req-ci-codex-1",
                        "output": {"content": "hello"},
                    },
                ]
            },
            timeout=2.0,
        )
        if codex.status_code != 202:
            raise RuntimeError(f"agent gateway expected 202, got {codex.status_code}: {codex.text}")
        _write_json(out_dir / "listener-codex-response.json", codex.json())

        env_payload = _run_cli(
            [
                "listen",
                "env",
                "--state-file",
                str(state_file),
                "--json",
            ]
        )
        _write_json(out_dir / "listener-env.json", json.loads(env_payload.stdout.strip()))
    finally:
        stop = _run_cli(
            [
                "listen",
                "stop",
                "--state-file",
                str(state_file),
                "--json",
            ],
            check=False,
        )
        if stop.stdout.strip():
            try:
                _write_json(out_dir / "listener-stop.json", json.loads(stop.stdout.strip()))
            except json.JSONDecodeError:
                (out_dir / "listener-stop.txt").write_text(stop.stdout, encoding="utf-8")

    _run_cli(
        [
            "assert",
            str(artifact_path),
            "--candidate",
            str(artifact_path),
            "--json",
        ]
    )
    replay_a = out_dir / "listener-replay-a.rpk"
    replay_b = out_dir / "listener-replay-b.rpk"
    _run_cli(
        [
            "replay",
            str(artifact_path),
            "--out",
            str(replay_a),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ]
    )
    _run_cli(
        [
            "replay",
            str(artifact_path),
            "--out",
            str(replay_b),
            "--seed",
            "19",
            "--fixed-clock",
            "2026-02-23T00:00:00Z",
        ]
    )
    determinism = _run_cli(
        [
            "assert",
            str(replay_a),
            "--candidate",
            str(replay_b),
            "--json",
        ]
    )
    _write_json(out_dir / "listener-replay-determinism.json", json.loads(determinism.stdout.strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
