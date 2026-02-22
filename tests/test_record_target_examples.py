from pathlib import Path
import subprocess
import sys

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_record_target_examples_run_directly() -> None:
    script = subprocess.run(
        [sys.executable, "examples/apps/record_target_script.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert script.returncode == 0, script.stderr

    module = subprocess.run(
        [sys.executable, "-m", "examples.apps.record_target_module"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0, module.stderr


def test_record_target_examples_capture_http_and_tool_boundaries(tmp_path: Path) -> None:
    runner = CliRunner()
    script_out = tmp_path / "script.rpk"
    module_out = tmp_path / "module.rpk"

    script_result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(script_out),
            "--",
            "python",
            "examples/apps/record_target_script.py",
        ],
    )
    assert script_result.exit_code == 0, script_result.output

    module_result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(module_out),
            "--",
            "python",
            "-m",
            "examples.apps.record_target_module",
        ],
    )
    assert module_result.exit_code == 0, module_result.output

    script_run = read_artifact(script_out)
    module_run = read_artifact(module_out)

    assert any(step.metadata.get("boundary") == "http" for step in script_run.steps)
    assert any(step.metadata.get("boundary") == "http" for step in module_run.steps)
    assert any(step.metadata.get("boundary") == "tool" for step in module_run.steps)
