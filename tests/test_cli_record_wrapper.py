from pathlib import Path

import httpx
import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_record_wrapper_executes_target_app_and_captures_steps(tmp_path: Path) -> None:
    out_path = tmp_path / "wrapped.rpk"

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
    assert len(run.steps) >= 4
    boundaries = {step.metadata.get("boundary") for step in run.steps}
    assert "http" in boundaries


def test_record_wrapper_restores_http_patches_after_run(tmp_path: Path) -> None:
    out_path = tmp_path / "wrapped-cleanup.rpk"
    original_requests = requests.sessions.Session.request
    original_httpx_client = httpx.Client.request
    original_httpx_async = httpx.AsyncClient.request

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
    assert requests.sessions.Session.request is original_requests
    assert httpx.Client.request is original_httpx_client
    assert httpx.AsyncClient.request is original_httpx_async
