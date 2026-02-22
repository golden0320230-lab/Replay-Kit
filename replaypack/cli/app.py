import json
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import runpy
import sys
import time
import traceback
import webbrowser
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

import typer

from replaypack.artifact import (
    ArtifactError,
    ArtifactMigrationError,
    DEFAULT_ARTIFACT_VERSION,
    SIGNING_KEY_ENV_VAR,
    migrate_artifact_file,
    redact_run_for_bundle,
    read_artifact,
    read_artifact_envelope,
    verify_artifact_signature,
    write_artifact,
    write_bundle_artifact,
)
from replaypack.capture import (
    InterceptionPolicy,
    RedactionPolicy,
    RedactionPolicyConfigError,
    build_demo_run,
    capture_run,
    intercept_httpx,
    intercept_requests,
    load_redaction_policy_from_file,
)
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
from replaypack.performance import (
    evaluate_benchmark_slowdown_gate,
    evaluate_slowdown_gate,
    run_benchmark_suite,
)
from replaypack.live_demo import build_live_demo_run
from replaypack.snapshot import (
    SnapshotConfigError,
    assert_snapshot_artifact,
    update_snapshot_artifact,
)
from replaypack.ui import UIServerConfig, build_ui_url, start_ui_server

app = typer.Typer(help="ReplayKit CLI")


@dataclass(slots=True)
class _OutputOptions:
    quiet: bool = False
    no_color: bool = False
    stable_json: bool = True


_OUTPUT_OPTIONS = _OutputOptions()
_PYTHON_COMMAND_TOKENS = {"python", "python3"}


@dataclass(frozen=True, slots=True)
class _RecordTargetInvocation:
    mode: str
    target: str
    args: tuple[str, ...]


def _resolve_cli_version() -> str:
    try:
        return package_version("replaykit")
    except PackageNotFoundError:
        from replaypack import __version__ as local_version

        return local_version


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(_resolve_cli_version(), color=False)
    raise typer.Exit()


def _load_redaction_policy(config_path: Path | None) -> RedactionPolicy | None:
    if config_path is None:
        return None
    try:
        return load_redaction_policy_from_file(config_path)
    except FileNotFoundError as error:
        raise ArtifactError(f"redaction config not found: {config_path}") from error
    except RedactionPolicyConfigError as error:
        raise ArtifactError(str(error)) from error


@app.callback()
def app_options(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show ReplayKit version and exit.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Suppress non-error text output.",
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable ANSI color output.",
    ),
    stable_json: bool = typer.Option(
        True,
        "--stable-json/--pretty-json",
        help="Emit stable compact JSON (or pretty JSON).",
    ),
) -> None:
    """Global output controls for all CLI commands."""
    _OUTPUT_OPTIONS.quiet = quiet
    _OUTPUT_OPTIONS.no_color = no_color
    _OUTPUT_OPTIONS.stable_json = stable_json


def _echo(message: str, *, err: bool = False, force: bool = False) -> None:
    if _OUTPUT_OPTIONS.quiet and not err and not force:
        return
    typer.echo(message, err=err, color=not _OUTPUT_OPTIONS.no_color)


def _echo_json(payload: dict[str, Any], *, err: bool = False) -> None:
    if _OUTPUT_OPTIONS.stable_json:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        )
    typer.echo(rendered, err=err, color=not _OUTPUT_OPTIONS.no_color)


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


def _parse_record_target_invocation(raw_args: list[str]) -> _RecordTargetInvocation:
    args = list(raw_args)
    if args and args[0] == "--":
        args = args[1:]
    if args and Path(args[0]).name in _PYTHON_COMMAND_TOKENS:
        args = args[1:]

    if not args:
        raise ValueError("missing target invocation; pass `-- python path/to/script.py`")

    if args[0] == "-m":
        if len(args) < 2 or not args[1].strip():
            raise ValueError("module mode requires a module name after -m")
        return _RecordTargetInvocation(
            mode="module",
            target=args[1].strip(),
            args=tuple(args[2:]),
        )

    return _RecordTargetInvocation(
        mode="script",
        target=args[0],
        args=tuple(args[1:]),
    )


def _run_record_target(invocation: _RecordTargetInvocation) -> int:
    previous_argv = list(sys.argv)
    try:
        if invocation.mode == "module":
            sys.argv = [invocation.target, *invocation.args]
            runpy.run_module(invocation.target, run_name="__main__", alter_sys=True)
        else:
            sys.argv = [invocation.target, *invocation.args]
            runpy.run_path(invocation.target, run_name="__main__")
        return 0
    except SystemExit as signal:
        code = signal.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        _echo(str(code), err=True)
        return 1
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        sys.argv = previous_argv


@app.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    }
)
def record(
    ctx: typer.Context,
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
    redaction_config: Path | None = typer.Option(
        None,
        "--redaction-config",
        help="Path to JSON redaction policy config.",
    ),
) -> None:
    """Record an execution run."""
    target_args = list(ctx.args)
    should_run_target = bool(target_args)

    if not demo and not should_run_target:
        _echo(
            "record failed: --no-demo requires a target command after `--`.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        redaction_policy = _load_redaction_policy(redaction_config)
        if should_run_target:
            invocation = _parse_record_target_invocation(target_args)
            run_id = f"run-record-{int(time.time() * 1000)}"
            target_exit_code = 0
            with capture_run(
                run_id=run_id,
                policy=InterceptionPolicy(capture_http_bodies=True),
                redaction_policy=redaction_policy,
            ) as capture_context:
                with ExitStack() as stack:
                    stack.enter_context(intercept_requests(context=capture_context))
                    stack.enter_context(intercept_httpx(context=capture_context))
                    target_exit_code = _run_record_target(invocation)
                run = capture_context.to_run()
        else:
            run = build_demo_run(redaction_policy=redaction_policy)
            target_exit_code = 0

        write_artifact(
            run,
            out,
            sign=sign,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
    except ArtifactError as error:
        _echo(f"record failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    if target_exit_code != 0:
        _echo(f"recorded artifact (target exit {target_exit_code}): {out}")
        raise typer.Exit(code=target_exit_code)

    _echo(f"recorded artifact: {out}")


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
        _echo(
            f"replay failed: invalid replay mode '{mode}'. Expected stub or hybrid.",
            err=True,
        )
        raise typer.Exit(code=2)

    rerun_type_values = tuple(rerun_type or [])
    rerun_step_id_values = tuple(rerun_step_id or [])
    if replay_mode == "hybrid":
        if rerun_from is None:
            _echo(
                "replay failed: --rerun-from is required for --mode hybrid.",
                err=True,
            )
            raise typer.Exit(code=2)
        if not rerun_type_values and not rerun_step_id_values:
            _echo(
                "replay failed: hybrid mode requires --rerun-type and/or --rerun-step-id.",
                err=True,
            )
            raise typer.Exit(code=2)
        unsupported_types = sorted(
            {step_type for step_type in rerun_type_values if step_type not in STEP_TYPES}
        )
        if unsupported_types:
            _echo(
                "replay failed: unsupported --rerun-type values: "
                f"{', '.join(unsupported_types)}",
                err=True,
            )
            raise typer.Exit(code=2)

    try:
        guardrail_mode: GuardrailMode = normalize_guardrail_mode(nondeterminism)
    except ValueError as error:
        _echo(f"replay failed: {error}", err=True)
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
                _echo_json(payload)
            else:
                _echo(message, err=True)
                _echo(
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
        _echo(f"replay failed: {error}", err=True)
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
        _echo_json(summary)
    else:
        _echo(f"replayed artifact ({replay_mode}): {out}")
        guardrail_text = render_guardrail_summary(
            mode=guardrail_mode,
            findings=guardrail_findings if guardrail_mode != "off" else [],
        )
        if guardrail_text:
            _echo(guardrail_text)


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
    redaction_config: Path | None = typer.Option(
        None,
        "--redaction-config",
        help="Path to JSON redaction policy config applied before diff output.",
    ),
) -> None:
    """Diff two runs and identify first divergence."""
    try:
        left_run = read_artifact(left)
        right_run = read_artifact(right)
        redaction_policy = _load_redaction_policy(redaction_config)
    except (ArtifactError, FileNotFoundError) as error:
        _echo(f"diff failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    if redaction_policy is not None:
        left_run = redact_run_for_bundle(left_run, policy=redaction_policy)
        right_run = redact_run_for_bundle(right_run, policy=redaction_policy)

    result = diff_runs(
        left_run,
        right_run,
        stop_at_first_divergence=first_divergence,
        max_changes_per_step=max(1, max_changes),
    )

    if json_output:
        _echo_json(result.to_dict())
        return

    _echo(render_diff_summary(result))
    _echo(render_first_divergence(result, max_changes=max_changes))


@app.command()
def benchmark(
    source: Path = typer.Option(
        Path("examples/runs/m2_capture_boundaries.rpk"),
        "--source",
        help="Source artifact path for replay/diff benchmark workloads.",
    ),
    out: Path = typer.Option(
        Path("runs/benchmark.json"),
        "--out",
        help="Output path for benchmark summary JSON.",
    ),
    iterations: int = typer.Option(
        5,
        "--iterations",
        min=1,
        help="Benchmark iterations per workload.",
    ),
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        help="Optional baseline benchmark JSON for slowdown comparison.",
    ),
    fail_on_slowdown: float | None = typer.Option(
        None,
        "--fail-on-slowdown",
        min=0.0,
        help=(
            "Fail if any workload mean runtime exceeds baseline by this percentage. "
            "Requires --baseline."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable benchmark output.",
    ),
) -> None:
    """Run representative record/replay/diff benchmarks and optional slowdown gate."""
    try:
        suite = run_benchmark_suite(
            source_artifact=source,
            iterations=iterations,
        )
    except (ArtifactError, FileNotFoundError, ValueError) as error:
        message = f"benchmark failed: {error}"
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=1) from error

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(suite.to_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    baseline_payload: dict[str, Any] | None = None
    if baseline is not None:
        try:
            baseline_payload = json.loads(baseline.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as error:
            message = f"benchmark failed: unable to read baseline benchmark ({error})"
            if json_output:
                _echo_json({"status": "error", "exit_code": 1, "message": message})
            else:
                _echo(message, err=True)
            raise typer.Exit(code=1) from error

    gate = evaluate_benchmark_slowdown_gate(
        suite,
        baseline_payload,
        threshold_percent=fail_on_slowdown,
    )

    payload = {
        "status": "fail" if gate.gate_failed else "pass",
        "exit_code": 1 if gate.gate_failed else 0,
        "out": str(out),
        "source": str(source),
        "benchmark": suite.to_dict(),
        "baseline_path": str(baseline) if baseline is not None else None,
        "slowdown_gate": gate.to_dict(),
    }

    if json_output:
        _echo_json(payload)
    else:
        _echo(f"benchmark artifact: {out}")
        _echo(
            "benchmark means (ms): "
            + ", ".join(
                f"{name}={stats.mean_ms:.3f}"
                for name, stats in sorted(suite.workloads.items())
            )
        )
        if fail_on_slowdown is not None:
            _echo(
                "benchmark slowdown gate: "
                f"status={gate.status} threshold={fail_on_slowdown:.3f}% "
                f"failing={','.join(gate.failing_workloads) or 'none'}"
            )

    if gate.gate_failed:
        raise typer.Exit(code=1)


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
    redaction_config: Path | None = typer.Option(
        None,
        "--redaction-config",
        help="Path to JSON redaction policy config.",
    ),
) -> None:
    """Bundle and redact a run artifact."""
    if redaction_config is not None and redact.strip().lower() != "default":
        _echo(
            "bundle failed: --redaction-config can only be used with --redact default.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        redaction_policy = _load_redaction_policy(redaction_config)
        envelope = write_bundle_artifact(
            artifact,
            out,
            redaction_profile=redact,
            redaction_policy=redaction_policy,
            redaction_profile_label="custom" if redaction_policy is not None else None,
            sign=sign,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
    except (ArtifactError, FileNotFoundError) as error:
        _echo(f"bundle failed: {error}", err=True)
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
        _echo_json(summary)
    else:
        _echo(f"bundle artifact: {out}")


@app.command()
def migrate(
    artifact: Path = typer.Argument(..., help="Path to source artifact (.rpk/.bundle)."),
    out: Path = typer.Option(
        Path("runs/migrated.rpk"),
        "--out",
        help="Output path for migrated artifact.",
    ),
    target_version: str = typer.Option(
        DEFAULT_ARTIFACT_VERSION,
        "--target-version",
        help="Target artifact schema version.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable migration summary.",
    ),
) -> None:
    """Migrate an artifact to the target schema version."""
    try:
        summary = migrate_artifact_file(
            artifact,
            out,
            target_version=target_version,
        )
    except (
        ArtifactError,
        ArtifactMigrationError,
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        message = f"migrate failed: {error}"
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=1) from error

    payload = {
        "status": "pass",
        "exit_code": 0,
        "source_path": str(artifact),
        "out": str(out),
        **summary.to_dict(),
    }
    if json_output:
        _echo_json(payload)
    else:
        _echo(
            "migrated artifact: "
            f"{artifact} -> {out} "
            f"(version {summary.source_version} -> {summary.target_version}, "
            f"steps={summary.total_steps}, "
            f"preserved_hashes={summary.preserved_step_hashes}, "
            f"recomputed_hashes={summary.recomputed_step_hashes})"
        )


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
            _echo_json({"status": "error", "valid": False, "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
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
        _echo_json(payload)
    else:
        if result.valid:
            _echo(f"verify passed: {artifact} ({result.status})")
        else:
            _echo(f"verify failed: {result.message}", err=True)

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
    fail_on_slowdown: float | None = typer.Option(
        None,
        "--fail-on-slowdown",
        min=0.0,
        help=(
            "Fail when candidate total duration exceeds baseline by this percentage "
            "(uses duration_ms/latency_ms/wall_time_ms metadata)."
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
        _echo(f"assert failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    if candidate is None:
        message = (
            "assert failed: missing candidate artifact. "
            "Provide --candidate PATH."
        )
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=1)

    try:
        baseline_run = read_artifact(baseline)
        candidate_run = read_artifact(candidate)
    except (ArtifactError, FileNotFoundError) as error:
        message = f"assert failed: {error}"
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
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
    slowdown_gate = evaluate_slowdown_gate(
        baseline_run,
        candidate_run,
        threshold_percent=fail_on_slowdown,
    )
    slowdown_failed = slowdown_gate.gate_failed

    payload = result.to_dict()
    payload["baseline_path"] = str(baseline)
    payload["candidate_path"] = str(candidate)
    payload["nondeterminism"] = guardrail_state
    payload["performance"] = slowdown_gate.to_dict()
    if guardrail_failed and result.passed:
        payload["status"] = "fail"
        payload["exit_code"] = 1
        payload["guardrail_failure"] = True
    if slowdown_failed and result.passed:
        payload["status"] = "fail"
        payload["exit_code"] = 1
        payload["slowdown_gate_failure"] = True

    if json_output:
        _echo_json(payload)
    else:
        if result.passed:
            mode = "assert passed (strict)" if strict else "assert passed"
            _echo(f"{mode}: baseline={baseline} candidate={candidate}")
        else:
            if strict and result.strict_failures and result.diff.identical:
                message = "assert failed: strict drift detected"
            else:
                message = "assert failed: divergence detected"
            _echo(
                f"{message} (baseline={baseline} candidate={candidate})",
                force=True,
            )
        if guardrail_failed and result.passed:
            _echo(
                "assert failed: nondeterminism indicators detected in fail mode "
                f"(baseline={baseline} candidate={candidate})",
                force=True,
            )
        if fail_on_slowdown is not None:
            slowdown_value = (
                f"{slowdown_gate.slowdown_percent:.3f}%"
                if slowdown_gate.slowdown_percent is not None
                else "n/a"
            )
            _echo(
                "performance gate: "
                f"baseline={slowdown_gate.baseline.total_duration_ms:.3f}ms "
                f"candidate={slowdown_gate.candidate.total_duration_ms:.3f}ms "
                f"slowdown={slowdown_value} "
                f"threshold={fail_on_slowdown:.3f}% "
                f"status={slowdown_gate.status}"
            )
        if slowdown_failed and result.passed:
            _echo(
                "assert failed: slowdown gate triggered "
                f"(baseline={baseline} candidate={candidate})",
                force=True,
            )
        _echo(render_diff_summary(result.diff))
        _echo(render_first_divergence(result.diff, max_changes=max_changes))
        strict_summary = _render_strict_failures(result, max_changes=max_changes)
        if strict_summary:
            _echo(strict_summary)
        guardrail_text = render_guardrail_summary(
            mode=guardrail_mode,
            findings=guardrail_findings if guardrail_mode != "off" else [],
        )
        if guardrail_text:
            _echo(guardrail_text)

    if not result.passed:
        raise typer.Exit(code=result.exit_code)
    if guardrail_failed or slowdown_failed:
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
            _echo_json({"status": "error", "exit_code": 2, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=2)

    try:
        baseline_run = read_artifact(baseline)
    except (ArtifactError, FileNotFoundError) as error:
        message = f"live-compare failed: {error}"
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
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
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
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
        _echo_json(payload)
    else:
        if result.passed:
            mode = "live-compare passed (strict)" if strict else "live-compare passed"
            _echo(f"{mode}: baseline={baseline} candidate={candidate_path}")
        else:
            if strict and result.strict_failures and result.diff.identical:
                message = "live-compare failed: strict drift detected"
            else:
                message = "live-compare failed: divergence detected"
            _echo(
                f"{message} (baseline={baseline} candidate={candidate_path})",
                force=True,
            )
        _echo(render_diff_summary(result.diff))
        _echo(render_first_divergence(result.diff, max_changes=max_changes))
        strict_summary = _render_strict_failures(result, max_changes=max_changes)
        if strict_summary:
            _echo(strict_summary)

    if not result.passed:
        raise typer.Exit(code=result.exit_code)


@app.command(name="live-demo")
def live_demo(
    out: Path = typer.Option(
        Path("runs/live-demo.rpk"),
        "--out",
        help="Output path for generated live-demo artifact.",
    ),
    provider: str = typer.Option(
        "fake",
        "--provider",
        help="Live-demo provider backend. Currently supported: fake.",
    ),
    stream: bool = typer.Option(
        False,
        "--stream/--no-stream",
        help="Capture fake provider in streaming mode.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable live-demo output.",
    ),
) -> None:
    """Generate a local provider-shaped capture artifact without target app wiring."""
    normalized_provider = provider.strip().lower()
    if normalized_provider != "fake":
        message = (
            f"live-demo failed: unsupported provider '{provider}'. Expected fake."
        )
        if json_output:
            _echo_json({"status": "error", "exit_code": 2, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=2)

    try:
        run = build_live_demo_run(provider=normalized_provider, stream=stream)
        write_artifact(
            run,
            out,
            metadata={
                "mode": "live-demo",
                "provider": normalized_provider,
                "stream": stream,
            },
        )
    except (ArtifactError, ValueError) as error:
        message = f"live-demo failed: {error}"
        if json_output:
            _echo_json({"status": "error", "exit_code": 1, "message": message})
        else:
            _echo(message, err=True)
        raise typer.Exit(code=1) from error

    payload = {
        "status": "ok",
        "exit_code": 0,
        "provider": normalized_provider,
        "stream": stream,
        "out": str(out),
        "run_id": run.id,
        "steps": len(run.steps),
    }
    if json_output:
        _echo_json(payload)
    else:
        _echo(f"live-demo artifact: {out}")


@app.command()
def snapshot(
    name: str = typer.Argument(..., help="Snapshot name (stored as <name>.rpk)."),
    candidate: Path = typer.Option(
        ...,
        "--candidate",
        "-c",
        help="Candidate .rpk artifact path.",
    ),
    snapshots_dir: Path = typer.Option(
        Path("snapshots"),
        "--snapshots-dir",
        help="Directory containing snapshot baseline artifacts.",
    ),
    update: bool = typer.Option(
        False,
        "--update",
        help="Create/update baseline from candidate artifact.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Enable strict drift checks: environment/runtime mismatch and "
            "per-step metadata drift (assert mode only)."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable snapshot output.",
    ),
    max_changes: int = typer.Option(
        8,
        "--max-changes",
        help="Maximum number of field-level changes to print in text mode.",
    ),
) -> None:
    """Create/update or assert artifact snapshots for regression testing."""
    try:
        if update:
            result = update_snapshot_artifact(
                snapshot_name=name,
                candidate_path=candidate,
                snapshots_dir=snapshots_dir,
            )
        else:
            result = assert_snapshot_artifact(
                snapshot_name=name,
                candidate_path=candidate,
                snapshots_dir=snapshots_dir,
                strict=strict,
                max_changes_per_step=max(1, max_changes),
            )
    except (SnapshotConfigError, ArtifactError, FileNotFoundError) as error:
        message = f"snapshot failed: {error}"
        payload = {
            "status": "error",
            "exit_code": 1,
            "action": "update" if update else "assert",
            "snapshot_name": name,
            "candidate_path": str(candidate),
            "baseline_path": str(snapshots_dir),
            "message": message,
        }
        if json_output:
            _echo_json(payload)
        else:
            _echo(message, err=True)
        raise typer.Exit(code=1) from error

    payload = result.to_dict()
    if json_output:
        _echo_json(payload)
    else:
        if result.status == "updated":
            _echo(
                "snapshot updated: "
                f"name={name} baseline={result.baseline_path} source={result.candidate_path}"
            )
        elif result.status == "pass":
            _echo(
                "snapshot passed: "
                f"name={name} baseline={result.baseline_path} candidate={result.candidate_path}"
            )
        elif result.status == "fail":
            _echo(
                "snapshot failed: "
                f"name={name} baseline={result.baseline_path} candidate={result.candidate_path}",
                force=True,
            )
        else:
            _echo(f"snapshot failed: {result.message}", err=True)

        if result.assertion is not None:
            _echo(render_diff_summary(result.assertion.diff))
            _echo(render_first_divergence(result.assertion.diff, max_changes=max_changes))
            strict_summary = _render_strict_failures(result.assertion, max_changes=max_changes)
            if strict_summary:
                _echo(strict_summary)

    if result.exit_code != 0:
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
            _echo(f"ui check ok: {ui_url}")
            return

        _echo(f"ui running: {ui_url}")

        if browser:
            webbrowser.open(ui_url)

        try:
            while True:
                time.sleep(0.25)
        except KeyboardInterrupt:
            _echo("ui stopped")


def main() -> None:
    app()
