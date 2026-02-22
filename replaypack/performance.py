"""Performance benchmarking and slowdown gate utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import tempfile
import time
from typing import Any, Literal

from replaypack.artifact import read_artifact, write_artifact
from replaypack.capture import build_demo_run
from replaypack.core.models import Run, Step
from replaypack.diff import diff_runs
from replaypack.replay import ReplayConfig, write_replay_stub_artifact

DURATION_METADATA_KEYS: tuple[str, ...] = (
    "duration_ms",
    "latency_ms",
    "wall_time_ms",
    "elapsed_ms",
)

SlowdownGateStatus = Literal[
    "not_requested",
    "within_threshold",
    "threshold_exceeded",
    "missing_metrics",
]

BenchmarkGateStatus = Literal[
    "not_requested",
    "within_threshold",
    "threshold_exceeded",
    "missing_baseline",
]


@dataclass(slots=True, frozen=True)
class TimingSummary:
    """Aggregate duration metadata extracted from run steps."""

    total_duration_ms: float
    measured_steps: int
    missing_steps: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_duration_ms": self.total_duration_ms,
            "measured_steps": self.measured_steps,
            "missing_steps": self.missing_steps,
        }


@dataclass(slots=True, frozen=True)
class SlowdownGateResult:
    """Result of evaluating candidate slowdown against baseline run timings."""

    status: SlowdownGateStatus
    threshold_percent: float | None
    slowdown_percent: float | None
    gate_failed: bool
    message: str
    baseline: TimingSummary
    candidate: TimingSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "threshold_percent": self.threshold_percent,
            "slowdown_percent": self.slowdown_percent,
            "gate_failed": self.gate_failed,
            "message": self.message,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
        }


@dataclass(slots=True, frozen=True)
class BenchmarkWorkloadStats:
    """Summary metrics for a single benchmark workload."""

    name: str
    iterations: int
    min_ms: float
    max_ms: float
    mean_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
        }


@dataclass(slots=True, frozen=True)
class BenchmarkSuiteResult:
    """Combined benchmark suite result across representative workloads."""

    source_artifact: str
    iterations: int
    workloads: dict[str, BenchmarkWorkloadStats]
    total_mean_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_artifact": self.source_artifact,
            "iterations": self.iterations,
            "total_mean_ms": self.total_mean_ms,
            "workloads": {
                name: stats.to_dict()
                for name, stats in sorted(self.workloads.items())
            },
        }


@dataclass(slots=True, frozen=True)
class BenchmarkGateResult:
    """Result of slowdown gate evaluation for benchmark suite."""

    status: BenchmarkGateStatus
    threshold_percent: float | None
    gate_failed: bool
    failing_workloads: list[str]
    workload_slowdown_percent: dict[str, float]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "threshold_percent": self.threshold_percent,
            "gate_failed": self.gate_failed,
            "failing_workloads": list(self.failing_workloads),
            "workload_slowdown_percent": dict(sorted(self.workload_slowdown_percent.items())),
            "message": self.message,
        }


def summarize_run_timing(run: Run) -> TimingSummary:
    """Summarize step-level duration metadata from a run."""
    total_duration_ms = 0.0
    measured_steps = 0
    missing_steps = 0

    for step in run.steps:
        duration = extract_step_duration_ms(step)
        if duration is None:
            missing_steps += 1
            continue
        total_duration_ms += duration
        measured_steps += 1

    return TimingSummary(
        total_duration_ms=round(total_duration_ms, 6),
        measured_steps=measured_steps,
        missing_steps=missing_steps,
    )


def evaluate_slowdown_gate(
    baseline_run: Run,
    candidate_run: Run,
    *,
    threshold_percent: float | None,
) -> SlowdownGateResult:
    """Evaluate candidate slowdown against baseline using duration metadata."""
    baseline = summarize_run_timing(baseline_run)
    candidate = summarize_run_timing(candidate_run)

    if threshold_percent is None:
        return SlowdownGateResult(
            status="not_requested",
            threshold_percent=None,
            slowdown_percent=None,
            gate_failed=False,
            message="slowdown gate not requested",
            baseline=baseline,
            candidate=candidate,
        )

    if baseline.measured_steps == 0 or candidate.measured_steps == 0 or baseline.total_duration_ms <= 0:
        return SlowdownGateResult(
            status="missing_metrics",
            threshold_percent=threshold_percent,
            slowdown_percent=None,
            gate_failed=True,
            message=(
                "slowdown gate requested but duration metadata is missing. "
                "Populate step metadata with duration_ms/latency_ms/wall_time_ms."
            ),
            baseline=baseline,
            candidate=candidate,
        )

    slowdown_percent = (
        (candidate.total_duration_ms - baseline.total_duration_ms)
        / baseline.total_duration_ms
        * 100.0
    )
    slowdown_percent = round(slowdown_percent, 6)

    exceeded = slowdown_percent > threshold_percent
    status: SlowdownGateStatus = "threshold_exceeded" if exceeded else "within_threshold"
    message = (
        "slowdown gate exceeded threshold"
        if exceeded
        else "slowdown gate within threshold"
    )

    return SlowdownGateResult(
        status=status,
        threshold_percent=threshold_percent,
        slowdown_percent=slowdown_percent,
        gate_failed=exceeded,
        message=message,
        baseline=baseline,
        candidate=candidate,
    )


def run_benchmark_suite(
    *,
    source_artifact: str | Path,
    iterations: int = 5,
) -> BenchmarkSuiteResult:
    """Run representative record/replay/diff benchmark workloads."""
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    source_path = Path(source_artifact)
    source_run = read_artifact(source_path)

    diverged_path = Path("examples/runs/m4_diverged_from_m2.rpk")
    diff_candidate = read_artifact(diverged_path) if diverged_path.exists() else source_run

    with tempfile.TemporaryDirectory(prefix="replaykit-benchmark-") as temp_dir:
        temp = Path(temp_dir)
        workloads = {
            "record": _measure_workload(
                "record",
                iterations,
                lambda i: write_artifact(
                    build_demo_run(),
                    temp / f"record-{i:03d}.rpk",
                ),
            ),
            "replay": _measure_workload(
                "replay",
                iterations,
                lambda i: write_replay_stub_artifact(
                    source_run,
                    temp / f"replay-{i:03d}.rpk",
                    config=ReplayConfig(seed=21, fixed_clock="2026-02-21T18:00:00Z"),
                ),
            ),
            "diff": _measure_workload(
                "diff",
                iterations,
                lambda _i: diff_runs(
                    source_run,
                    diff_candidate,
                    stop_at_first_divergence=False,
                    max_changes_per_step=8,
                ),
            ),
        }

    total_mean_ms = round(sum(workload.mean_ms for workload in workloads.values()), 6)
    return BenchmarkSuiteResult(
        source_artifact=str(source_path),
        iterations=iterations,
        workloads=workloads,
        total_mean_ms=total_mean_ms,
    )


def evaluate_benchmark_slowdown_gate(
    current: BenchmarkSuiteResult,
    baseline_payload: dict[str, Any] | None,
    *,
    threshold_percent: float | None,
) -> BenchmarkGateResult:
    """Evaluate benchmark slowdown against a baseline benchmark payload."""
    if threshold_percent is None:
        return BenchmarkGateResult(
            status="not_requested",
            threshold_percent=None,
            gate_failed=False,
            failing_workloads=[],
            workload_slowdown_percent={},
            message="benchmark slowdown gate not requested",
        )

    if baseline_payload is None:
        return BenchmarkGateResult(
            status="missing_baseline",
            threshold_percent=threshold_percent,
            gate_failed=True,
            failing_workloads=[],
            workload_slowdown_percent={},
            message="benchmark slowdown gate requested but baseline benchmark is missing",
        )

    baseline_workloads = _extract_baseline_workloads(baseline_payload)
    if not baseline_workloads:
        return BenchmarkGateResult(
            status="missing_baseline",
            threshold_percent=threshold_percent,
            gate_failed=True,
            failing_workloads=[],
            workload_slowdown_percent={},
            message="baseline benchmark payload does not include workloads",
        )

    slowdowns: dict[str, float] = {}
    failures: list[str] = []

    for name, current_stats in current.workloads.items():
        baseline_entry = baseline_workloads.get(name)
        baseline_mean = _to_float(baseline_entry.get("mean_ms")) if baseline_entry else None
        if baseline_mean is None or baseline_mean <= 0:
            failures.append(name)
            continue
        slowdown_percent = ((current_stats.mean_ms - baseline_mean) / baseline_mean) * 100.0
        slowdown_percent = round(slowdown_percent, 6)
        slowdowns[name] = slowdown_percent
        if slowdown_percent > threshold_percent:
            failures.append(name)

    if failures:
        return BenchmarkGateResult(
            status="threshold_exceeded",
            threshold_percent=threshold_percent,
            gate_failed=True,
            failing_workloads=sorted(set(failures)),
            workload_slowdown_percent=slowdowns,
            message="benchmark slowdown exceeded threshold for one or more workloads",
        )

    return BenchmarkGateResult(
        status="within_threshold",
        threshold_percent=threshold_percent,
        gate_failed=False,
        failing_workloads=[],
        workload_slowdown_percent=slowdowns,
        message="benchmark slowdown within threshold",
    )


def extract_step_duration_ms(step: Step) -> float | None:
    """Extract best-effort step duration in milliseconds from metadata."""
    for key in DURATION_METADATA_KEYS:
        if key not in step.metadata:
            continue
        value = _to_float(step.metadata.get(key))
        if value is None:
            continue
        if value < 0:
            continue
        return round(value, 6)
    return None


def _measure_workload(
    name: str,
    iterations: int,
    fn: Any,
) -> BenchmarkWorkloadStats:
    samples: list[float] = []
    for index in range(iterations):
        start = time.perf_counter()
        fn(index)
        end = time.perf_counter()
        samples.append((end - start) * 1000.0)

    min_ms = round(min(samples), 6)
    max_ms = round(max(samples), 6)
    mean_ms = round(sum(samples) / len(samples), 6)
    return BenchmarkWorkloadStats(
        name=name,
        iterations=iterations,
        min_ms=min_ms,
        max_ms=max_ms,
        mean_ms=mean_ms,
    )


def _extract_baseline_workloads(payload: dict[str, Any]) -> dict[str, Any]:
    if "workloads" in payload and isinstance(payload["workloads"], dict):
        return payload["workloads"]
    benchmark = payload.get("benchmark")
    if isinstance(benchmark, dict):
        workloads = benchmark.get("workloads")
        if isinstance(workloads, dict):
            return workloads
    return {}


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        if not math.isfinite(parsed):
            return None
        return parsed
    return None
