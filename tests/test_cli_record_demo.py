from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_record_demo_writes_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "demo.rpk"

    runner = CliRunner()
    result = runner.invoke(app, ["record", "--out", str(out_path)])

    assert result.exit_code == 0
    assert out_path.exists()

    run = read_artifact(out_path)
    assert run.id == "run-demo-001"
    assert len(run.steps) == 6


def test_record_without_demo_flag_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["record", "--no-demo"])

    assert result.exit_code == 2
    assert "only --demo is supported in M2" in result.output
