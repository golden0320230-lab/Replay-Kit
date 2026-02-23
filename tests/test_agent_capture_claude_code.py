from __future__ import annotations

import json
from pathlib import Path
import sys

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_agent_capture_claude_code_fixture_writes_timeline_artifact(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "agent-claude-code.rpk"
    fixture = Path("tests/fixtures/agents/fake_claude_code_agent.py")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "capture",
            "--agent",
            "claude-code",
            "--out",
            str(out_path),
            "--json",
            "--",
            sys.executable,
            str(fixture),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["artifact_path"] == str(out_path)

    run = read_artifact(out_path)
    step_types = [step.type for step in run.steps]
    assert step_types[0] == "agent.command"
    assert "model.request" in step_types
    assert "model.response" in step_types
    assert "tool.request" in step_types
    assert "tool.response" in step_types
    assert step_types[-1] == "output.final"
    assert run.source == "agent.capture"
    assert run.agent == "claude-code"

