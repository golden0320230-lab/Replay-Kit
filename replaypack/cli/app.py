import typer

app = typer.Typer(help="ReplayKit CLI")


@app.command()
def record() -> None:
    """Record an execution run (stub)."""
    typer.echo("record: not implemented yet")


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


@app.command()
def assert_run() -> None:
    """Assert behavior against baseline (stub)."""
    typer.echo("assert: not implemented yet")


@app.command()
def ui() -> None:
    """Launch local diff UI (stub)."""
    typer.echo("ui: not implemented yet")


def main() -> None:
    app()
