from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_record_target_golden_path_local_only(tmp_path: Path) -> None:
    out_path = tmp_path / "target-record.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(out_path),
            "--",
            "python",
            "examples/apps/minimal_app.py",
        ],
    )

    assert result.exit_code == 0, result.output
    assert out_path.exists()

    run = read_artifact(out_path)
    http_steps = [
        step
        for step in run.steps
        if step.metadata.get("boundary") == "http"
    ]
    assert len(http_steps) >= 2
    for step in http_steps:
        url = step.metadata.get("url", "")
        assert isinstance(url, str)
        assert "127.0.0.1" in url
