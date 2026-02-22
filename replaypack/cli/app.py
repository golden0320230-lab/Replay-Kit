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
from replaypack.core.types import STEP_TYPES
from replaypack.diff import (
    AssertionResult,
    assert_runs,
    diff_runs,
    render_diff_summary,
    render_first_divergence,
)
from replaypack.guardrails import (
    GuardrailMode,
    detect_diff_nondeterminism,
    detect_run_nondeterminism,
    guardrail_payload,
    normalize_guardrail_mode,
    render_guardrail_summary,
)
from replaypack.replay import (
    HybridReplayPolicy,
    ReplayConfig,
    ReplayError,
    write_replay_hybrid_artifact,
    write_replay_stub_artifact,
)
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
    mode: str = typer.Option(
        "stub",
        "--mode",
        help="Replay mode: stub or hybrid.",
    ),
    rerun_from: Path | None = typer.Option(
        None,
        "--rerun-from",
        help="Rerun source artifact path (required in hybrid mode).",
    ),
    rerun_type: list[str] | None = typer.Option(
        None,
        "--rerun-type",
        help=(
            "Repeatable step-type selector to rerun in hybrid mode "
            "(for example: model.response)."
        ),
    ),
    rerun_step_id: list[str] | None = typer.Option(
        None,
        "--rerun-step-id",
        help="Repeatable step-id selector to rerun in hybrid mode.",
    ),
    nondeterminism: str = typer.Option(
        "off",
        "--nondeterminism",
        help="Determinism guardrail mode: off, warn, fail.",
    ),
) -> None:
    """Replay a recorded artifact in offline stub or hybrid mode."""
    replay_mode = mode.strip().lower()
    if replay_mode not in {"stub", "hybrid"}:
        typer.echo(
            f"replay failed: invalid replay mode '{mode}'. Expected stub or hybrid.",
            err=True,
        )
        raise typer.Exit(code=2)

    rerun_type_values = tuple(rerun_type or [])
    rerun_step_id_values = tuple(rerun_step_id or [])
    if replay_mode == "hybrid":
        if rerun_from is None:
            typer.echo(
                "replay failed: --rerun-from is required for --mode hybrid.",
                err=True,
            )
            raise typer.Exit(code=2)
        if not rerun_type_values and not rerun_step_id_values:
            typer.echo(
                "replay failed: hybrid mode requires --rerun-type and/or --rerun-step-id.",
                err=True,
            )
            raise typer.Exit(code=2)
        unsupported_types = sorted(
            {step_type for step_type in rerun_type_values if step_type not in STEP_TYPES}
        )
        if unsupported_types:
            typer.echo(
                "replay failed: unsupported --rerun-type values: "
                f"{', '.join(unsupported_types)}",
                err=True,
            )
            raise typer.Exit(code=2)

    try:
        guardrail_mode: GuardrailMode = normalize_guardrail_mode(nondeterminism)
    except ValueError as error:
        typer.echo(f"replay failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    rerun_run = None
    policy = None
    try:
        source_run = read_artifact(artifact)
        if replay_mode == "hybrid":
            rerun_run = read_artifact(rerun_from)
            policy = HybridReplayPolicy(
                rerun_step_types=rerun_type_values,
                rerun_step_ids=rerun_step_id_values,
            )
        guardrail_findings = (
            detect_run_nondeterminism(source_run, run_label="source")
            if guardrail_mode != "off"
            else []
        )
        if guardrail_mode != "off" and rerun_run is not None:
            guardrail_findings.extend(
                detect_run_nondeterminism(rerun_run, run_label="rerun")
            )
        if guardrail_mode == "fail" and guardrail_findings:
            message = (
                "replay failed: nondeterminism indicators detected in replay inputs. "
                "Use --nondeterminism warn to continue with warning output."
            )
            if json_output:
                payload = {
                    "mode": replay_mode,
                    "status": "error",
                    "message": message,
                    "exit_code": 1,
                    "nondeterminism": guardrail_payload(
                        mode=guardrail_mode,
                        findings=guardrail_findings,
                    ),
                }
                typer.echo(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            else:
                typer.echo(message, err=True)
                typer.echo(
                    render_guardrail_summary(
                        mode=guardrail_mode,
                        findings=guardrail_findings,
                    ),
                    err=True,
                )
            raise typer.Exit(code=1)

        config = ReplayConfig(seed=seed, fixed_clock=fixed_clock)
        if replay_mode == "hybrid":
            envelope = write_replay_hybrid_artifact(
                source_run,
                rerun_run,
                str(out),
                config=config,
                policy=policy,
            )
        else:
            envelope = write_replay_stub_artifact(source_run, str(out), config=config)
    except (ArtifactError, ReplayError, FileNotFoundError) as error:
        typer.echo(f"replay failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    summary = {
        "mode": replay_mode,
        "source_run_id": source_run.id,
        "replay_run_id": envelope["payload"]["run"]["id"],
        "steps": len(source_run.steps),
        "seed": seed,
        "fixed_clock": config.fixed_clock,
        "out": str(out),
        "nondeterminism": guardrail_payload(
            mode=guardrail_mode,
            findings=guardrail_findings if guardrail_mode != "off" else [],
        ),
    }
    if replay_mode == "hybrid" and rerun_run is not None and policy is not None:
        summary["rerun_from"] = str(rerun_from)
        summary["rerun_from_run_id"] = rerun_run.id
        summary["rerun_step_types"] = list(policy.rerun_step_types)
        summary["rerun_step_ids"] = list(policy.rerun_step_ids)

    if json_output:
        typer.echo(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    else:
        typer.echo(f"replayed artifact ({replay_mode}): {out}")
        guardrail_text = render_guardrail_summary(
            mode=guardrail_mode,
            findings=guardrail_findings if guardrail_mode != "off" else [],
        )
        if guardrail_text:
            typer.echo(guardrail_text)


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
    nondeterminism: str = typer.Option(
        "off",
        "--nondeterminism",
        help="Determinism guardrail mode: off, warn, fail.",
    ),
) -> None:
    """Assert candidate behavior matches baseline artifact."""
    try:
        guardrail_mode: GuardrailMode = normalize_guardrail_mode(nondeterminism)
    except ValueError as error:
        typer.echo(f"assert failed: {error}", err=True)
        raise typer.Exit(code=2) from error

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
    guardrail_findings = []
    if guardrail_mode != "off":
        guardrail_findings.extend(
            detect_run_nondeterminism(baseline_run, run_label="baseline")
        )
        guardrail_findings.extend(
            detect_run_nondeterminism(candidate_run, run_label="candidate")
        )
        guardrail_findings.extend(detect_diff_nondeterminism(result.diff, source="diff"))

    guardrail_state = guardrail_payload(
        mode=guardrail_mode,
        findings=guardrail_findings if guardrail_mode != "off" else [],
    )
    guardrail_failed = guardrail_mode == "fail" and bool(guardrail_findings)

    payload = result.to_dict()
    payload["baseline_path"] = str(baseline)
    payload["candidate_path"] = str(candidate)
    payload["nondeterminism"] = guardrail_state
    if guardrail_failed and result.passed:
        payload["status"] = "fail"
        payload["exit_code"] = 1
        payload["guardrail_failure"] = True

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
        if guardrail_failed and result.passed:
            typer.echo(
                "assert failed: nondeterminism indicators detected in fail mode "
                f"(baseline={baseline} candidate={candidate})"
            )
        typer.echo(render_diff_summary(result.diff))
        typer.echo(render_first_divergence(result.diff, max_changes=max_changes))
        strict_summary = _render_strict_failures(result, max_changes=max_changes)
        if strict_summary:
            typer.echo(strict_summary)
        guardrail_text = render_guardrail_summary(
            mode=guardrail_mode,
            findings=guardrail_findings if guardrail_mode != "off" else [],
        )
        if guardrail_text:
            typer.echo(guardrail_text)

    if not result.passed:
        raise typer.Exit(code=result.exit_code)
    if guardrail_failed:
        raise typer.Exit(code=1)


@app.command(name="live-compare")
def live_compare(
    baseline: Path = typer.Argument(..., help="Path to baseline .rpk artifact."),
    candidate: Path | None = typer.Option(
        None,
        "--candidate",
        "-c",
        help="Optional candidate .rpk artifact path (if omitted, --live-demo is used).",
    ),
    out: Path = typer.Option(
        Path("runs/live-compare-candidate.rpk"),
        "--out",
        help="Output path when generating live demo candidate artifact.",
    ),
    live_demo: bool = typer.Option(
        True,
        "--live-demo/--no-live-demo",
        help="Generate candidate via built-in deterministic demo capture.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Enable strict drift checks: environment/runtime mismatch and "
            "per-step metadata drift."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable live-compare output.",
    ),
    max_changes: int = typer.Option(
        8,
        "--max-changes",
        help="Maximum number of field-level changes to print in text mode.",
    ),
) -> None:
    """Run live execution and compare against a baseline artifact."""
    if candidate is None and not live_demo:
        message = (
            "live-compare failed: missing live input. "
            "Provide --candidate PATH or enable --live-demo."
        )
        if json_output:
            typer.echo(
                json.dumps(
                    {"status": "error", "exit_code": 2, "message": message},
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(code=2)

    try:
        baseline_run = read_artifact(baseline)
    except (ArtifactError, FileNotFoundError) as error:
        message = f"live-compare failed: {error}"
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

    live_mode = "artifact"
    candidate_path = candidate
    try:
        if candidate is not None:
            candidate_run = read_artifact(candidate)
        else:
            live_run = build_demo_run()
            write_artifact(
                live_run,
                out,
                metadata={
                    "mode": "live-compare-demo",
                    "baseline_run_id": baseline_run.id,
                },
            )
            candidate_run = live_run.with_hashed_steps()
            candidate_path = out
            live_mode = "demo"
    except (ArtifactError, FileNotFoundError) as error:
        message = f"live-compare failed: {error}"
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
    payload["candidate_path"] = str(candidate_path)
    payload["live_mode"] = live_mode
    payload["exit_code"] = result.exit_code

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    else:
        if result.passed:
            mode = "live-compare passed (strict)" if strict else "live-compare passed"
            typer.echo(f"{mode}: baseline={baseline} candidate={candidate_path}")
        else:
            if strict and result.strict_failures and result.diff.identical:
                message = "live-compare failed: strict drift detected"
            else:
                message = "live-compare failed: divergence detected"
            typer.echo(f"{message} (baseline={baseline} candidate={candidate_path})")
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
