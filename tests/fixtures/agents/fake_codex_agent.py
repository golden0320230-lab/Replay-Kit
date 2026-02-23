"""Fixture codex-like agent emitting deterministic JSONL events."""

from __future__ import annotations

import json


def main() -> None:
    events = [
        {
            "type": "model.request",
            "input": {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hello"}],
            },
            "metadata": {"provider": "openai"},
        },
        {
            "type": "model.response",
            "request_id": "req-codex-001",
            "output": {"content": "Hello from codex fixture"},
            "metadata": {"provider": "openai"},
        },
        {
            "type": "tool.request",
            "input": {"tool": "shell", "args": ["echo", "hello"]},
        },
        {
            "type": "tool.response",
            "tool": "shell",
            "output": {"stdout": "hello", "exit_code": 0},
        },
    ]
    for event in events:
        print(json.dumps(event, ensure_ascii=True))


if __name__ == "__main__":
    main()

