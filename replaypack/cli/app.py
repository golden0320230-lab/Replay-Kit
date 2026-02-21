import json
from pathlib import Path

import typer

from replaypack.artifact import ArtifactError, read_artifact, write_artifact, write_bundle_artifact
from replaypack.capture import build_demo_run
from replaypack.diff import assert_runs, diff_runs, render_diff_summary, render_first_divergence
from replaypack.replay import ReplayConfig, ReplayError, write_replay_stub_artifact

app = typer.Typer(help="ReplayKit CLI")


@app.command()
def record(
    out: Path = typer.Option(
        Path("runs/demo-recording.rpk"),
        "--out",
        help="Output path for the recorded artifact.",
    ),
    demo: bool = typer.Option(
        True,
        "--demo/--no-demo",
        help="Use the built-in deterministic demo capture workflow.",
    ),
) -> None:
    """Record an execution run."""
    if not demo:
        typer.echo("record: only --demo is supported in M2")
        raise typer.Exit(code=2)

    run = build_demo_run()
    write_artifact(run, out)
    typer.echo(f"recorded artifact: {out}")


@app.command()
def replay(
    artifact: Path = typer.Argument(..., help="Path to source .rpk artifact."),
    out: Path = typer.Option(
        Path("runs/replay-output.rpk"),
        "--out",
        help="Output path for replayed artifact.",
    ),
    seed: int = typer.Option(
        0,
        "--seed",
        help="Deterministic replay seed.",
    ),
    fixed_clock: str = typer.Option(
        "2026-01-01T00:00:00Z",
        "--fixed-clock",
        help="Fixed clock for replay timestamp (ISO-8601 with timezone).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable replay summary.",
    ),
) -> None:
    """Replay a recorded artifact in offline stub mode."""
    try:
        source_run = read_artifact(artifact)
        config = ReplayConfig(seed=seed, fixed_clock=fixed_clock)
        envelope = write_replay_stub_artifact(source_run, str(out), config=config)
    except (ArtifactError, ReplayError, FileNotFoundError) as error:
        typer.echo(f"replay failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    summary = {
        "mode": "stub",
        "source_run_id": source_run.id,
        "replay_run_id": envelope["payload"]["run"]["id"],
        "steps": len(source_run.steps),
        "seed": seed,
        "fixed_clock": config.fixed_clock,
        "out": str(out),
    }
    if json_output:
        typer.echo(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    else:
        typer.echo(f"replayed artifact: {out}")


@app.command()
def diff(
    left: Path = typer.Argument(..., help="Path to left .rpk artifact."),
    right: Path = typer.Argument(..., help="Path to right .rpk artifact."),
    first_divergence: bool = typer.Option(
        False,
        "--first-divergence",
        help="Stop at and print only first divergent step context.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable diff output.",
    ),
    max_changes: int = typer.Option(
        8,
        "--max-changes",
        help="Maximum number of field-level changes to print in text mode.",
    ),
) -> None:
    """Diff two runs and identify first divergence."""
    try:
        left_run = read_artifact(left)
        right_run = read_artifact(right)
    except (ArtifactError, FileNotFoundError) as error:
        typer.echo(f"diff failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    result = diff_runs(
        left_run,
        right_run,
        stop_at_first_divergence=first_divergence,
        max_changes_per_step=max(1, max_changes),
    )

    if json_output:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=True, sort_keys=True))
        return

    typer.echo(render_diff_summary(result))
    typer.echo(render_first_divergence(result, max_changes=max_changes))


@app.command()
def bundle(
    artifact: Path = typer.Argument(..., help="Path to source .rpk artifact."),
    out: Path = typer.Option(
        Path("runs/incident.bundle"),
        "--out",
        help="Output path for bundled artifact.",
    ),
    redact: str = typer.Option(
        "default",
        "--redact",
        help="Redaction profile: default or none.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable bundle summary.",
    ),
) -> None:
    """Bundle and redact a run artifact."""
    try:
        envelope = write_bundle_artifact(artifact, out, redaction_profile=redact)
    except (ArtifactError, FileNotFoundError) as error:
        typer.echo(f"bundle failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    summary = {
        "mode": "bundle",
        "source_run_id": envelope["metadata"]["source_run_id"],
        "bundle_run_id": envelope["payload"]["run"]["id"],
        "steps": len(envelope["payload"]["run"]["steps"]),
        "redaction_profile": envelope["metadata"]["redaction_profile"],
        "out": str(out),
    }

    if json_output:
        typer.echo(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    else:
        typer.echo(f"bundle artifact: {out}")


@app.command(name="assert")
def assert_run(
    baseline: Path = typer.Argument(..., help="Path to baseline .rpk artifact."),
    candidate: Path | None = typer.Option(
        None,
        "--candidate",
        "-c",
        help="Path to candidate .rpk artifact to compare against baseline.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable assertion output.",
    ),
    max_changes: int = typer.Option(
        8,
        "--max-changes",
        help="Maximum number of field-level changes to print in text mode.",
    ),
) -> None:
    """Assert candidate behavior matches baseline artifact."""
    if candidate is None:
        message = (
            "assert failed: missing candidate artifact. "
            "Provide --candidate PATH."
        )
        if json_output:
            typer.echo(
                json.dumps(
                    {"status": "error", "exit_code": 1, "message": message},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(code=1)

    try:
        baseline_run = read_artifact(baseline)
        candidate_run = read_artifact(candidate)
    except (ArtifactError, FileNotFoundError) as error:
        message = f"assert failed: {error}"
        if json_output:
            typer.echo(
                json.dumps(
                    {"status": "error", "exit_code": 1, "message": message},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(code=1) from error

    result = assert_runs(
        baseline_run,
        candidate_run,
        max_changes_per_step=max(1, max_changes),
    )

    payload = result.to_dict()
    payload["baseline_path"] = str(baseline)
    payload["candidate_path"] = str(candidate)

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        if result.passed:
            typer.echo(
                "assert passed: "
                f"baseline={baseline} candidate={candidate}"
            )
        else:
            typer.echo(
                "assert failed: divergence detected "
                f"(baseline={baseline} candidate={candidate})"
            )
        typer.echo(render_diff_summary(result.diff))
        typer.echo(render_first_divergence(result.diff, max_changes=max_changes))

    if not result.passed:
        raise typer.Exit(code=result.exit_code)


@app.command()
def ui() -> None:
    """Launch local diff UI (stub)."""
    typer.echo("ui: not implemented yet")


def main() -> None:
    app()
