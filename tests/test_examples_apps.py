from pathlib import Path
import subprocess
import sys

from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_minimal_example_app_runs_without_external_network() -> None:
    app_path = Path("examples/apps/minimal_app.py")
    assert app_path.exists()

    result = subprocess.run(
        [sys.executable, str(app_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_minimal_target_app_runs_without_external_network() -> None:
    app_path = Path("examples/apps/minimal_target_app.py")
    assert app_path.exists()

    result = subprocess.run(
        [sys.executable, str(app_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_minimal_target_app_is_recordable_with_http_boundaries(tmp_path: Path) -> None:
    out_path = tmp_path / "minimal-target.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "record",
            "--out",
            str(out_path),
            "--",
            "python",
            "examples/apps/minimal_target_app.py",
        ],
    )

    assert result.exit_code == 0, result.output
    run = read_artifact(out_path)
    http_urls = [
        str(step.metadata.get("url", ""))
        for step in run.steps
        if step.metadata.get("boundary") == "http"
    ]
    assert len(http_urls) >= 2
    assert all("127.0.0.1" in url for url in http_urls)
