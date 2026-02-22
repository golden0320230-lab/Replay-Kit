import json
from pathlib import Path
import time
import webbrowser

import typer

from replaypack.artifact import (
    ArtifactError,
    SIGNING_KEY_ENV_VAR,
    read_artifact,
    read_artifact_envelope,
    verify_artifact_signature,
    write_artifact,
    write_bundle_artifact,
)
from replaypack.capture import build_demo_run
from replaypack.diff import (
    AssertionResult,
    assert_runs,
    diff_runs,
    render_diff_summary,
    render_first_divergence,
)
from replaypack.replay import ReplayConfig, ReplayError, write_replay_stub_artifact
from replaypack.ui import UIServerConfig, build_ui_url, start_ui_server

app = typer.Typer(help="ReplayKit CLI")


def _render_strict_failures(result: AssertionResult, *, max_changes: int) -> str:
    if not result.strict_failures:
        return ""

    limit = max(1, max_changes)
    lines = [f"strict drift checks failed: {len(result.strict_failures)}"]

    for failure in result.strict_failures[:limit]:
        lines.append(f"- [{failure.kind}] {failure.path}")
        lines.append(
            f"  left={json.dumps(failure.left, ensure_ascii=True, sort_keys=True)}"
        )
        lines.append(
            f"  right={json.dumps(failure.right, ensure_ascii=True, sort_keys=True)}"
        )

    remaining = len(result.strict_failures) - limit
    if remaining > 0:
        lines.append(f"... {remaining} additional strict mismatch(es) not shown")

    return "\n".join(lines)


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
    sign: bool = typer.Option(
        False,
        "--sign",
        help="Attach HMAC signature to the output artifact.",
    ),
    signing_key: str | None = typer.Option(
        None,
        "--signing-key",
        envvar=SIGNING_KEY_ENV_VAR,
        help=f"HMAC signing key. Can also be set via {SIGNING_KEY_ENV_VAR}.",
    ),
    signing_key_id: str = typer.Option(
        "default",
        "--signing-key-id",
        envvar="REPLAYKIT_SIGNING_KEY_ID",
        help="Optional signing key identifier stored in artifact signature metadata.",
    ),
) -> None:
    """Record an execution run."""
    if not demo:
        typer.echo("record: only --demo is supported in M2")
        raise typer.Exit(code=2)

    run = build_demo_run()
    try:
        write_artifact(
            run,
            out,
            sign=sign,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
    except ArtifactError as error:
        typer.echo(f"record failed: {error}", err=True)
        raise typer.Exit(code=1) from error
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
    sign: bool = typer.Option(
        False,
        "--sign",
        help="Attach HMAC signature to bundled artifact.",
    ),
    signing_key: str | None = typer.Option(
        None,
        "--signing-key",
        envvar=SIGNING_KEY_ENV_VAR,
        help=f"HMAC signing key. Can also be set via {SIGNING_KEY_ENV_VAR}.",
    ),
    signing_key_id: str = typer.Option(
        "default",
        "--signing-key-id",
        envvar="REPLAYKIT_SIGNING_KEY_ID",
        help="Optional signing key identifier stored in artifact signature metadata.",
    ),
) -> None:
    """Bundle and redact a run artifact."""
    try:
        envelope = write_bundle_artifact(
            artifact,
            out,
            redaction_profile=redact,
            sign=sign,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
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


@app.command()
def verify(
    artifact: Path = typer.Argument(..., help="Path to signed .rpk/.bundle artifact."),
    signing_key: str | None = typer.Option(
        None,
        "--signing-key",
        envvar=SIGNING_KEY_ENV_VAR,
        help=f"HMAC signing key. Can also be set via {SIGNING_KEY_ENV_VAR}.",
    ),
    require_signature: bool = typer.Option(
        True,
        "--require-signature/--allow-unsigned",
        help="Require signature presence (default) or allow unsigned artifacts.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable verification output.",
    ),
) -> None:
    """Verify artifact checksum and optional HMAC signature."""
    try:
        envelope = read_artifact_envelope(artifact)
    except (ArtifactError, FileNotFoundError, json.JSONDecodeError) as error:
        message = f"verify failed: {error}"
        if json_output:
            typer.echo(
                json.dumps(
                    {"status": "error", "valid": False, "exit_code": 1, "message": message},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(code=1) from error

    result = verify_artifact_signature(
        envelope,
        signing_key=signing_key,
        require_signature=require_signature,
    )

    payload = result.to_dict()
    payload["artifact_path"] = str(artifact)
    payload["exit_code"] = 0 if result.valid else 1

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        if result.valid:
            typer.echo(f"verify passed: {artifact} ({result.status})")
        else:
            typer.echo(f"verify failed: {result.message}", err=True)

    if not result.valid:
        raise typer.Exit(code=1)


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
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Enable strict drift checks: environment/runtime mismatch and "
            "per-step metadata drift."
        ),
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
        strict=strict,
        max_changes_per_step=max(1, max_changes),
    )

    payload = result.to_dict()
    payload["baseline_path"] = str(baseline)
    payload["candidate_path"] = str(candidate)

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        if result.passed:
            mode = "assert passed (strict)" if strict else "assert passed"
            typer.echo(f"{mode}: baseline={baseline} candidate={candidate}")
        else:
            if strict and result.strict_failures and result.diff.identical:
                message = "assert failed: strict drift detected"
            else:
                message = "assert failed: divergence detected"
            typer.echo(f"{message} (baseline={baseline} candidate={candidate})")
        typer.echo(render_diff_summary(result.diff))
        typer.echo(render_first_divergence(result.diff, max_changes=max_changes))
        strict_summary = _render_strict_failures(result, max_changes=max_changes)
        if strict_summary:
            typer.echo(strict_summary)

    if not result.passed:
        raise typer.Exit(code=result.exit_code)


@app.command()
def ui(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host interface to bind local UI server.",
    ),
    port: int = typer.Option(
        4310,
        "--port",
        help="Port for local UI server (0 selects an ephemeral port).",
    ),
    left: Path | None = typer.Option(
        None,
        "--left",
        help="Optional default left artifact path to pre-fill UI.",
    ),
    right: Path | None = typer.Option(
        None,
        "--right",
        help="Optional default right artifact path to pre-fill UI.",
    ),
    browser: bool = typer.Option(
        False,
        "--browser/--no-browser",
        help="Open the local UI URL in default browser.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Start server, verify startup path, then exit.",
    ),
) -> None:
    """Launch local Git-diff style UI for replay artifact inspection."""
    # Check mode should avoid fixed-port collisions in CI/local test runners.
    effective_port = 0 if check else port
    config = UIServerConfig(host=host, port=effective_port, base_dir=Path.cwd())

    with start_ui_server(config) as (server, _thread):
        bound_host, bound_port = server.server_address
        ui_url = build_ui_url(
            bound_host,
            bound_port,
            left=str(left) if left else None,
            right=str(right) if right else None,
        )

        if check:
            typer.echo(f"ui check ok: {ui_url}")
            return

        typer.echo(f"ui running: {ui_url}")

        if browser:
            webbrowser.open(ui_url)

        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            typer.echo("ui stopped")


def main() -> None:
    app()
