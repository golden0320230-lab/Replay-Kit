from pathlib import Path

import typer

from replaypack.artifact import write_artifact
from replaypack.capture import build_demo_run

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
def replay() -> None:
    """Replay a recorded run (stub)."""
    typer.echo("replay: not implemented yet")


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
