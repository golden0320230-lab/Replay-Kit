"""Deterministic replay engine with stub and hybrid modes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
import socket
from typing import Iterator, Literal

from replaypack.artifact import write_artifact
from replaypack.core.canonical import canonical_json
from replaypack.core.models import Run, Step
from replaypack.core.types import STEP_TYPES
from replaypack.replay.exceptions import ReplayConfigError

ReplayMode = Literal["stub", "hybrid"]


@dataclass(slots=True)
class ReplayConfig:
    """Configuration for deterministic replay execution."""

    seed: int = 0
    fixed_clock: str = "2026-01-01T00:00:00Z"

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int):
            raise ReplayConfigError("seed must be an integer")
        self.fixed_clock = normalize_fixed_clock(self.fixed_clock)


@dataclass(slots=True)
class HybridReplayPolicy:
    """Selection policy for hybrid replay rerun boundaries."""

    rerun_step_types: tuple[str, ...] = field(default_factory=tuple)
    rerun_step_ids: tuple[str, ...] = field(default_factory=tuple)
    strict_alignment: bool = True

    def __post_init__(self) -> None:
        self.rerun_step_types = _normalize_selector_tuple(self.rerun_step_types)
        self.rerun_step_ids = _normalize_selector_tuple(self.rerun_step_ids)

        unsupported = [step_type for step_type in self.rerun_step_types if step_type not in STEP_TYPES]
        if unsupported:
            raise ReplayConfigError(
                f"Unsupported rerun step type(s): {', '.join(sorted(unsupported))}"
            )

        if not self.has_selectors():
            raise ReplayConfigError(
                "Hybrid replay requires at least one selector "
                "(rerun_step_types or rerun_step_ids)."
            )

    def has_selectors(self) -> bool:
        return bool(self.rerun_step_types) or bool(self.rerun_step_ids)

    def should_rerun(self, step: Step) -> bool:
        return step.type in self.rerun_step_types or step.id in self.rerun_step_ids

    def to_dict(self) -> dict[str, object]:
        return {
            "rerun_step_types": list(self.rerun_step_types),
            "rerun_step_ids": list(self.rerun_step_ids),
            "strict_alignment": self.strict_alignment,
        }


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
        replay_steps = _replay_steps_stub(source_run)

    replay_id = _deterministic_stub_replay_id(source_run, cfg)

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


def replay_hybrid_run(
    source_run: Run,
    rerun_run: Run,
    *,
    config: ReplayConfig | None = None,
    policy: HybridReplayPolicy | None = None,
) -> Run:
    """Build deterministic hybrid replay using rerun boundaries from another run."""
    cfg = config or ReplayConfig()
    effective_policy = policy or HybridReplayPolicy(rerun_step_types=("model.response",))

    with deterministic_runtime(seed=cfg.seed), offline_network_guard():
        replay_steps = _replay_steps_hybrid(
            source_run=source_run,
            rerun_run=rerun_run,
            policy=effective_policy,
        )

    replay_id = _deterministic_hybrid_replay_id(
        source_run=source_run,
        rerun_run=rerun_run,
        config=cfg,
        replay_steps=replay_steps,
        policy=effective_policy,
    )

    environment = {
        **source_run.environment_fingerprint,
        "replay_mode": "hybrid",
        "replay_offline": True,
        "source_run_id": source_run.id,
        "rerun_from_run_id": rerun_run.id,
    }

    runtime = {
        **source_run.runtime_versions,
        "replay_mode": "hybrid",
        "replay_seed": str(cfg.seed),
        "replay_fixed_clock": cfg.fixed_clock,
        "replay_rerun_step_types": ",".join(effective_policy.rerun_step_types),
        "replay_rerun_step_ids": ",".join(effective_policy.rerun_step_ids),
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


def write_replay_hybrid_artifact(
    source_run: Run,
    rerun_run: Run,
    out_path: str,
    *,
    config: ReplayConfig | None = None,
    policy: HybridReplayPolicy | None = None,
) -> dict:
    """Replay a source run in hybrid mode and persist deterministic artifact."""
    cfg = config or ReplayConfig()
    effective_policy = policy or HybridReplayPolicy(rerun_step_types=("model.response",))
    replay_run = replay_hybrid_run(
        source_run,
        rerun_run,
        config=cfg,
        policy=effective_policy,
    )
    return write_artifact(
        replay_run,
        out_path,
        metadata={
            "replay_mode": "hybrid",
            "source_run_id": source_run.id,
            "rerun_from_run_id": rerun_run.id,
            "seed": cfg.seed,
            "fixed_clock": cfg.fixed_clock,
            "rerun_step_types": list(effective_policy.rerun_step_types),
            "rerun_step_ids": list(effective_policy.rerun_step_ids),
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


def _replay_steps_stub(source_run: Run) -> list[Step]:
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
                    "source_step_id": source_step.id,
                    "replay_strategy": "stub",
                },
            ).with_hash()
        )
    return replay_steps


def _replay_steps_hybrid(*, source_run: Run, rerun_run: Run, policy: HybridReplayPolicy) -> list[Step]:
    if policy.strict_alignment and len(source_run.steps) != len(rerun_run.steps):
        raise ReplayConfigError(
            "Hybrid replay requires source and rerun runs to have equal step count "
            "when strict_alignment=True."
        )

    replay_steps: list[Step] = []
    rerun_count = 0

    for index, source_step in enumerate(source_run.steps, start=1):
        rerun_selected = policy.should_rerun(source_step)
        metadata = dict(source_step.metadata)
        replay_input = source_step.input
        replay_output = source_step.output

        if rerun_selected:
            if index > len(rerun_run.steps):
                raise ReplayConfigError(
                    "Hybrid replay could not align rerun step at index "
                    f"{index} (rerun run has {len(rerun_run.steps)} steps)."
                )
            rerun_step = rerun_run.steps[index - 1]
            if rerun_step.type != source_step.type:
                raise ReplayConfigError(
                    "Hybrid replay step type mismatch at index "
                    f"{index}: source={source_step.type} rerun={rerun_step.type}"
                )
            replay_input = rerun_step.input
            replay_output = rerun_step.output
            metadata = dict(rerun_step.metadata)
            metadata["rerun_step_id"] = rerun_step.id
            metadata["rerun_from_run_id"] = rerun_run.id
            rerun_count += 1

        metadata["replay_strategy"] = "rerun" if rerun_selected else "stub"
        metadata["source_step_id"] = source_step.id

        replay_steps.append(
            Step(
                id=f"step-{index:06d}",
                type=source_step.type,
                input=replay_input,
                output=replay_output,
                metadata=metadata,
            ).with_hash()
        )

    if rerun_count == 0:
        raise ReplayConfigError(
            "Hybrid replay selectors matched zero source steps; "
            "adjust rerun_step_types/rerun_step_ids."
        )

    return replay_steps


def _normalize_selector_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = sorted({str(value).strip() for value in values if str(value).strip()})
    return tuple(normalized)


def _source_fingerprint(run: Run) -> str:
    return canonical_json(
        {
            "source_id": run.id,
            "steps": [_stable_step_hash(step) for step in run.steps],
        }
    )


def _deterministic_stub_replay_id(source_run: Run, config: ReplayConfig) -> str:
    source_fingerprint = _source_fingerprint(source_run)
    payload = {
        "mode": "stub",
        "source_fingerprint": source_fingerprint,
        "seed": config.seed,
        "fixed_clock": config.fixed_clock,
    }
    digest = _deterministic_digest(payload)
    return f"replay-{digest}"


def _deterministic_hybrid_replay_id(
    *,
    source_run: Run,
    rerun_run: Run,
    config: ReplayConfig,
    replay_steps: list[Step],
    policy: HybridReplayPolicy,
) -> str:
    source_fingerprint = _source_fingerprint(source_run)
    rerun_fingerprint = canonical_json(
        {
            "rerun_run_id": rerun_run.id,
            "steps": [_stable_step_hash(step) for step in rerun_run.steps],
        }
    )
    payload = {
        "mode": "hybrid",
        "source_fingerprint": source_fingerprint,
        "rerun_fingerprint": rerun_fingerprint,
        "replay_steps": [step.hash for step in replay_steps],
        "policy": policy.to_dict(),
        "seed": config.seed,
        "fixed_clock": config.fixed_clock,
    }
    digest = _deterministic_digest(payload)
    return f"replay-{digest}"


def _deterministic_digest(payload: dict[str, object]) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:12]


def _stable_step_hash(step: Step) -> str:
    return step.hash or step.with_hash().hash or ""
