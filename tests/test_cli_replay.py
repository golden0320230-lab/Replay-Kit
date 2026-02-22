import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact, write_artifact
from replaypack.cli.app import app
from replaypack.core.models import Run, Step


def _nondeterministic_source_run() -> Run:
    return Run(
        id="run-cli-replay-guardrail-001",
        timestamp="2026-02-22T18:15:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={
            "python": "3.12.0",
            "replaykit": "0.1.0",
            "uses_random": "true",
        },
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "req-001"},
                output={"content": "hi"},
                metadata={"provider": "openai"},
            ),
        ],
    )


def _hybrid_source_and_rerun_runs() -> tuple[Run, Run]:
    source = Run(
        id="run-cli-hybrid-source-001",
        timestamp="2026-02-22T19:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.0", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-src-001",
                type="model.request",
                input={"prompt": "hi"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-src-002",
                type="model.response",
                input={"request_id": "req-src-001"},
                output={"content": "baseline"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-src-003",
                type="output.final",
                input={"response_id": "resp-src-001"},
                output={"text": "baseline"},
                metadata={},
            ),
        ],
    )

    rerun = Run(
        id="run-cli-hybrid-rerun-001",
        timestamp="2026-02-22T19:02:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.0", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-rerun-001",
                type="model.request",
                input={"prompt": "hi"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-rerun-002",
                type="model.response",
                input={"request_id": "req-rerun-001"},
                output={"content": "rerun"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-rerun-003",
                type="output.final",
                input={"response_id": "resp-rerun-001"},
                output={"text": "rerun"},
                metadata={},
            ),
        ],
    )

    return source, rerun


def test_cli_replay_writes_stub_artifact(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--seed",
            "11",
            "--fixed-clock",
            "2026-02-21T17:15:00Z",
        ],
    )

    assert result.exit_code == 0
    assert out.exists()

    replay_run = read_artifact(out)
    assert replay_run.runtime_versions["replay_mode"] == "stub"
    assert replay_run.runtime_versions["replay_seed"] == "11"
    assert replay_run.timestamp == "2026-02-21T17:15:00.000000Z"


def test_cli_replay_json_output_mode(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--seed",
            "5",
            "--fixed-clock",
            "2026-02-21T17:20:00Z",
            "--json",
        ],
    )

    assert result.exit_code == 0
    summary = json.loads(result.stdout.strip())
    assert summary["mode"] == "stub"
    assert summary["seed"] == 5
    assert summary["out"] == str(out)


def test_cli_replay_returns_non_zero_on_invalid_clock(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--fixed-clock",
            "2026-02-21T17:20:00",
        ],
    )

    assert result.exit_code == 1
    combined_output = result.stdout + result.stderr
    assert "replay failed" in combined_output


def test_cli_replay_guardrail_warn_mode_reports_findings(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    out = tmp_path / "replayed.rpk"
    write_artifact(_nondeterministic_source_run(), source)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--nondeterminism",
            "warn",
            "--json",
        ],
    )

    assert result.exit_code == 0
    summary = json.loads(result.stdout.strip())
    assert summary["nondeterminism"]["status"] == "warn"
    assert summary["nondeterminism"]["count"] >= 1
    assert out.exists()


def test_cli_replay_guardrail_fail_mode_blocks_replay(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    out = tmp_path / "replayed.rpk"
    write_artifact(_nondeterministic_source_run(), source)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--nondeterminism",
            "fail",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["nondeterminism"]["status"] == "fail"
    assert out.exists() is False


def test_cli_replay_rejects_invalid_guardrail_mode(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")
    out = tmp_path / "replayed.rpk"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--out",
            str(out),
            "--nondeterminism",
            "invalid",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "Invalid nondeterminism mode" in combined


def test_cli_replay_rejects_invalid_mode(tmp_path: Path) -> None:
    source = Path("examples/runs/m2_capture_boundaries.rpk")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--mode",
            "invalid",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "invalid replay mode" in combined


def test_cli_replay_hybrid_mode_writes_artifact(tmp_path: Path) -> None:
    source_run, rerun_run = _hybrid_source_and_rerun_runs()
    source = tmp_path / "source.rpk"
    rerun = tmp_path / "rerun.rpk"
    out = tmp_path / "hybrid.rpk"
    write_artifact(source_run, source)
    write_artifact(rerun_run, rerun)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--mode",
            "hybrid",
            "--rerun-from",
            str(rerun),
            "--rerun-type",
            "model.response",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["mode"] == "hybrid"
    assert payload["rerun_from"] == str(rerun)
    assert payload["rerun_step_types"] == ["model.response"]

    replay_run = read_artifact(out)
    assert replay_run.runtime_versions["replay_mode"] == "hybrid"
    assert replay_run.steps[1].output == {"content": "rerun"}
    assert replay_run.steps[1].metadata["replay_strategy"] == "rerun"
    assert replay_run.steps[0].metadata["replay_strategy"] == "stub"


def test_cli_replay_hybrid_requires_rerun_from(tmp_path: Path) -> None:
    source_run, _ = _hybrid_source_and_rerun_runs()
    source = tmp_path / "source.rpk"
    write_artifact(source_run, source)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--mode",
            "hybrid",
            "--rerun-type",
            "model.response",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "--rerun-from is required" in combined


def test_cli_replay_hybrid_requires_selector(tmp_path: Path) -> None:
    source_run, rerun_run = _hybrid_source_and_rerun_runs()
    source = tmp_path / "source.rpk"
    rerun = tmp_path / "rerun.rpk"
    write_artifact(source_run, source)
    write_artifact(rerun_run, rerun)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--mode",
            "hybrid",
            "--rerun-from",
            str(rerun),
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "requires --rerun-type and/or --rerun-step-id" in combined


def test_cli_replay_hybrid_rejects_unknown_rerun_type(tmp_path: Path) -> None:
    source_run, rerun_run = _hybrid_source_and_rerun_runs()
    source = tmp_path / "source.rpk"
    rerun = tmp_path / "rerun.rpk"
    write_artifact(source_run, source)
    write_artifact(rerun_run, rerun)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "replay",
            str(source),
            "--mode",
            "hybrid",
            "--rerun-from",
            str(rerun),
            "--rerun-type",
            "bad.type",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "unsupported --rerun-type values" in combined
