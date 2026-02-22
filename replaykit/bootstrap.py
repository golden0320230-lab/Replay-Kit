"""Bootstrap runner for in-process capture of arbitrary Python targets."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import runpy
import sys
import traceback
from typing import Sequence

from replaypack.artifact import ArtifactError, SIGNING_KEY_ENV_VAR, write_artifact
from replaypack.capture import (
    InterceptionPolicy,
    capture_run,
    intercept_httpx,
    intercept_requests,
    load_redaction_policy_from_file,
)

_PYTHON_LIKE_TOKENS = {"python", "python3"}
_SUPPORTED_INTERCEPTS = ("httpx", "requests")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m replaykit.bootstrap",
        description=(
            "Capture a Python script/module in-process and write a ReplayKit artifact."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for recorded artifact (.rpk).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier. Defaults to a generated bootstrap id.",
    )
    parser.add_argument(
        "--timestamp",
        default=None,
        help="Optional fixed run timestamp (ISO-8601).",
    )
    parser.add_argument(
        "--module",
        default=None,
        help="Run a module by name (equivalent to python -m <module>).",
    )
    parser.add_argument(
        "--intercept",
        action="append",
        choices=_SUPPORTED_INTERCEPTS,
        default=None,
        help=(
            "Repeatable interceptor names. Defaults to both requests and httpx when omitted."
        ),
    )
    parser.add_argument(
        "--redaction-config",
        default=None,
        type=Path,
        help="Optional path to JSON redaction policy config.",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Attach HMAC signature to output artifact.",
    )
    parser.add_argument(
        "--signing-key",
        default=os.getenv(SIGNING_KEY_ENV_VAR),
        help=f"Signing key used when --sign is set (or env {SIGNING_KEY_ENV_VAR}).",
    )
    parser.add_argument(
        "--signing-key-id",
        default=os.getenv("REPLAYKIT_SIGNING_KEY_ID", "default"),
        help="Optional signing key identifier stored in signature metadata.",
    )
    parser.add_argument(
        "target",
        nargs=argparse.REMAINDER,
        help=(
            "Target invocation. Use -- to separate bootstrap flags. "
            "Examples: -- script.py arg1 OR -- -m package.module arg1"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        spec = _resolve_target_spec(module_flag=args.module, raw_target=args.target)
    except ValueError as error:
        parser.error(str(error))
        return 2

    intercepts = tuple(args.intercept or _SUPPORTED_INTERCEPTS)
    run_id = args.run_id or _default_run_id()

    redaction_policy = None
    if args.redaction_config is not None:
        try:
            redaction_policy = load_redaction_policy_from_file(args.redaction_config)
        except FileNotFoundError:
            print(
                f"bootstrap failed: redaction config not found: {args.redaction_config}",
                file=sys.stderr,
            )
            return 1
        except ArtifactError as error:
            print(f"bootstrap failed: {error}", file=sys.stderr)
            return 1
        except ValueError as error:
            print(f"bootstrap failed: {error}", file=sys.stderr)
            return 1

    exit_code = 1
    with capture_run(
        run_id=run_id,
        timestamp=args.timestamp,
        policy=InterceptionPolicy(capture_http_bodies=True),
        redaction_policy=redaction_policy,
    ) as capture_context:
        with ExitStack() as stack:
            if "requests" in intercepts:
                stack.enter_context(intercept_requests(context=capture_context))
            if "httpx" in intercepts:
                stack.enter_context(intercept_httpx(context=capture_context))
            exit_code = _execute_target(spec)

        run = capture_context.to_run()

    try:
        write_artifact(
            run,
            args.out,
            sign=bool(args.sign),
            signing_key=args.signing_key,
            signing_key_id=args.signing_key_id,
            metadata={
                "bootstrap": True,
                "target_mode": spec.mode,
                "target": spec.target,
                "target_args": list(spec.args),
                "intercepts": list(intercepts),
            },
        )
    except (ArtifactError, OSError) as error:
        print(f"bootstrap failed: {error}", file=sys.stderr)
        return 1

    return exit_code


class _TargetSpec:
    def __init__(self, *, mode: str, target: str, args: tuple[str, ...]) -> None:
        self.mode = mode
        self.target = target
        self.args = args


def _resolve_target_spec(
    *,
    module_flag: str | None,
    raw_target: Sequence[str],
) -> _TargetSpec:
    target = list(raw_target)
    if target and target[0] == "--":
        target = target[1:]

    if target and Path(target[0]).name in _PYTHON_LIKE_TOKENS:
        target = target[1:]

    if module_flag:
        module_name = module_flag.strip()
        if not module_name:
            raise ValueError("--module must be non-empty")
        return _TargetSpec(mode="module", target=module_name, args=tuple(target))

    if not target:
        raise ValueError("missing target invocation; pass script path or -m module")

    if target[0] == "-m":
        if len(target) < 2 or not target[1].strip():
            raise ValueError("module mode requires a module name after -m")
        return _TargetSpec(
            mode="module",
            target=target[1],
            args=tuple(target[2:]),
        )

    script_path = target[0]
    return _TargetSpec(mode="script", target=script_path, args=tuple(target[1:]))


def _execute_target(spec: _TargetSpec) -> int:
    previous_argv = list(sys.argv)
    try:
        if spec.mode == "module":
            sys.argv = [spec.target, *spec.args]
            runpy.run_module(spec.target, run_name="__main__", alter_sys=True)
        else:
            sys.argv = [spec.target, *spec.args]
            runpy.run_path(spec.target, run_name="__main__")
        return 0
    except SystemExit as signal:
        return _system_exit_code(signal)
    except Exception:  # pragma: no cover - covered by subprocess tests via return code
        traceback.print_exc()
        return 1
    finally:
        sys.argv = previous_argv


def _system_exit_code(signal: SystemExit) -> int:
    code = signal.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(str(code), file=sys.stderr)
    return 1


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"run-bootstrap-{stamp}"


if __name__ == "__main__":
    raise SystemExit(main())
