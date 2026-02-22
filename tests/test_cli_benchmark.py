import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.cli.app import app


def test_cli_benchmark_writes_summary_and_json_output(tmp_path: Path) -> None:
    out = tmp_path / "benchmark.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--iterations",
            "1",
            "--source",
            "examples/runs/m2_capture_boundaries.rpk",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["out"] == str(out)
    assert out.exists()
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert set(summary["workloads"].keys()) == {"record", "replay", "diff"}


def test_cli_benchmark_slowdown_gate_fails(tmp_path: Path) -> None:
    out = tmp_path / "benchmark.json"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "workloads": {
                    "record": {"mean_ms": 0.0001},
                    "replay": {"mean_ms": 0.0001},
                    "diff": {"mean_ms": 0.0001},
                }
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--iterations",
            "1",
            "--source",
            "examples/runs/m2_capture_boundaries.rpk",
            "--out",
            str(out),
            "--baseline",
            str(baseline),
            "--fail-on-slowdown",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "fail"
    assert payload["slowdown_gate"]["gate_failed"] is True
    assert payload["slowdown_gate"]["status"] == "threshold_exceeded"


def test_cli_benchmark_returns_error_for_missing_baseline(tmp_path: Path) -> None:
    out = tmp_path / "benchmark.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--iterations",
            "1",
            "--source",
            "examples/runs/m2_capture_boundaries.rpk",
            "--out",
            str(out),
            "--baseline",
            str(tmp_path / "missing-baseline.json"),
            "--fail-on-slowdown",
            "10",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "unable to read baseline benchmark" in payload["message"]
