import json
from pathlib import Path

import typer

from replaypack.artifact import ArtifactError, read_artifact, write_artifact
from replaypack.capture import build_demo_run
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
def diff() -> None:
    """Diff two runs and find first divergence (stub)."""
    typer.echo("diff: not implemented yet")


@app.command()
def bundle() -> None:
    """Bundle and redact a run artifact (stub)."""
    typer.echo("bundle: not implemented yet")


@app.command(name="assert")
def assert_run() -> None:
    """Assert behavior against baseline (stub)."""
    typer.echo("assert: not implemented yet")


@app.command()
def ui() -> None:
    """Launch local diff UI (stub)."""
    typer.echo("ui: not implemented yet")


def main() -> None:
    app()
