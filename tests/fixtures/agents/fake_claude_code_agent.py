"""Fixture claude-code-like agent emitting deterministic JSONL events."""

from __future__ import annotations

import json


def main() -> None:
    events = [
        {
            "type": "model.request",
            "input": {
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": "hello"}],
            },
            "metadata": {"provider": "anthropic"},
        },
        {
            "type": "model.response",
            "request_id": "req-claude-001",
            "output": {"content": "Hello from claude-code fixture"},
            "metadata": {"provider": "anthropic"},
        },
        {
            "type": "tool.request",
            "input": {"tool": "read_file", "args": ["README.md"]},
        },
        {
            "type": "tool.response",
            "tool": "read_file",
            "output": {"content": "fixture content", "ok": True},
        },
    ]
    for event in events:
        print(json.dumps(event, ensure_ascii=True))


if __name__ == "__main__":
    main()

