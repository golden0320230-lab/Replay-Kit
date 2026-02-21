"""Deterministic offline stub replay engine."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import random
import socket
from typing import Iterator

from replaypack.artifact import write_artifact
from replaypack.core.canonical import canonical_json
from replaypack.core.models import Run, Step
from replaypack.replay.exceptions import ReplayConfigError


@dataclass(slots=True)
class ReplayConfig:
    """Configuration for deterministic replay execution."""

    seed: int = 0
    fixed_clock: str = "2026-01-01T00:00:00Z"

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int):
            raise ReplayConfigError("seed must be an integer")
        self.fixed_clock = normalize_fixed_clock(self.fixed_clock)


def normalize_fixed_clock(value: str) -> str:
    parse_target = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parse_target)
    except ValueError as exc:
        raise ReplayConfigError(
            "fixed_clock must be a valid ISO-8601 timestamp with timezone"
        ) from exc

    if parsed.tzinfo is None:
        raise ReplayConfigError("fixed_clock must include timezone information")

    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def replay_stub_run(source_run: Run, *, config: ReplayConfig | None = None) -> Run:
    """Build a deterministic offline replay run from a recorded source run."""
    cfg = config or ReplayConfig()

    with deterministic_runtime(seed=cfg.seed), offline_network_guard():
        replay_steps = _replay_steps(source_run)

    replay_id = _deterministic_replay_id(source_run, cfg)

    environment = {
        **source_run.environment_fingerprint,
        "replay_mode": "stub",
        "replay_offline": True,
        "source_run_id": source_run.id,
    }

    runtime = {
        **source_run.runtime_versions,
        "replay_mode": "stub",
        "replay_seed": str(cfg.seed),
        "replay_fixed_clock": cfg.fixed_clock,
    }

    return Run(
        id=replay_id,
        timestamp=cfg.fixed_clock,
        environment_fingerprint=environment,
        runtime_versions=runtime,
        steps=replay_steps,
    )


def write_replay_stub_artifact(
    source_run: Run,
    out_path: str,
    *,
    config: ReplayConfig | None = None,
) -> dict:
    """Replay a source run in stub mode and persist a deterministic artifact."""
    cfg = config or ReplayConfig()
    replay_run = replay_stub_run(source_run, config=cfg)
    return write_artifact(
        replay_run,
        out_path,
        metadata={
            "replay_mode": "stub",
            "source_run_id": source_run.id,
            "seed": cfg.seed,
            "fixed_clock": cfg.fixed_clock,
        },
    )


@contextmanager
def deterministic_runtime(*, seed: int) -> Iterator[None]:
    """Control Python RNG for deterministic replay execution."""
    previous_state = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(previous_state)


@contextmanager
def offline_network_guard() -> Iterator[None]:
    """Block outbound network connection attempts during replay."""
    original_create_connection = socket.create_connection

    def blocked(*_args, **_kwargs):
        raise RuntimeError("offline replay forbids outbound network calls")

    socket.create_connection = blocked
    try:
        yield
    finally:
        socket.create_connection = original_create_connection


def _replay_steps(source_run: Run) -> list[Step]:
    replay_steps: list[Step] = []
    for index, source_step in enumerate(source_run.steps, start=1):
        replay_steps.append(
            Step(
                id=f"step-{index:06d}",
                type=source_step.type,
                input=source_step.input,
                output=source_step.output,
                metadata={
                    **source_step.metadata,
                    "replay_mode": "stub",
                    "source_step_id": source_step.id,
                },
            ).with_hash()
        )
    return replay_steps


def _deterministic_replay_id(source_run: Run, config: ReplayConfig) -> str:
    source_fingerprint = canonical_json(
        {
            "source_id": source_run.id,
            "steps": [step.hash for step in source_run.steps],
        }
    )

    import hashlib

    digest = hashlib.sha256(
        canonical_json(
            {
                "source_fingerprint": source_fingerprint,
                "seed": config.seed,
                "fixed_clock": config.fixed_clock,
            }
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"replay-{digest}"
