import json
from pathlib import Path

from replaypack.artifact import read_artifact
from replaypack.performance import (
    evaluate_benchmark_slowdown_gate,
    evaluate_slowdown_gate,
    run_benchmark_suite,
    summarize_run_timing,
)


def test_summarize_run_timing_from_artifact_with_metadata() -> None:
    run = read_artifact(Path("examples/runs/minimal_v1.rpk"))
    # fixture includes step metadata with duration/latency fields.
    run.steps[0].metadata["duration_ms"] = 10
    run.steps[1].metadata["latency_ms"] = "7.5"
    summary = summarize_run_timing(run)

    assert summary.total_duration_ms == 17.5
    assert summary.measured_steps == 2
    assert summary.missing_steps == 0


def test_evaluate_slowdown_gate_within_and_exceeded() -> None:
    baseline = read_artifact(Path("examples/runs/minimal_v1.rpk"))
    candidate = read_artifact(Path("examples/runs/minimal_v1.rpk"))
    baseline.steps[0].metadata["duration_ms"] = 100
    baseline.steps[1].metadata["duration_ms"] = 100
    candidate.steps[0].metadata["duration_ms"] = 130
    candidate.steps[1].metadata["duration_ms"] = 130

    within = evaluate_slowdown_gate(
        baseline,
        candidate,
        threshold_percent=40.0,
    )
    exceeded = evaluate_slowdown_gate(
        baseline,
        candidate,
        threshold_percent=20.0,
    )

    assert within.status == "within_threshold"
    assert within.gate_failed is False
    assert within.slowdown_percent == 30.0
    assert exceeded.status == "threshold_exceeded"
    assert exceeded.gate_failed is True


def test_evaluate_slowdown_gate_missing_metrics() -> None:
    baseline = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))
    candidate = read_artifact(Path("examples/runs/m2_capture_boundaries.rpk"))

    result = evaluate_slowdown_gate(
        baseline,
        candidate,
        threshold_percent=10.0,
    )
    assert result.status == "missing_metrics"
    assert result.gate_failed is True


def test_run_benchmark_suite_returns_representative_workloads() -> None:
    suite = run_benchmark_suite(
        source_artifact=Path("examples/runs/m2_capture_boundaries.rpk"),
        iterations=1,
    )

    assert set(suite.workloads.keys()) == {"record", "replay", "diff"}
    assert suite.total_mean_ms >= 0.0
    assert all(stats.mean_ms >= 0.0 for stats in suite.workloads.values())


def test_evaluate_benchmark_slowdown_gate() -> None:
    suite = run_benchmark_suite(
        source_artifact=Path("examples/runs/m2_capture_boundaries.rpk"),
        iterations=1,
    )

    tiny_baseline = {
        "workloads": {
            "record": {"mean_ms": 0.0001},
            "replay": {"mean_ms": 0.0001},
            "diff": {"mean_ms": 0.0001},
        }
    }
    pass_baseline = {
        "workloads": {
            "record": {"mean_ms": 999999.0},
            "replay": {"mean_ms": 999999.0},
            "diff": {"mean_ms": 999999.0},
        }
    }

    failed = evaluate_benchmark_slowdown_gate(
        suite,
        tiny_baseline,
        threshold_percent=0.0,
    )
    passed = evaluate_benchmark_slowdown_gate(
        suite,
        pass_baseline,
        threshold_percent=0.0,
    )

    assert failed.gate_failed is True
    assert failed.status == "threshold_exceeded"
    assert failed.failing_workloads
    assert passed.gate_failed is False
    assert passed.status == "within_threshold"


def test_benchmark_gate_supports_nested_payload_shape() -> None:
    suite = run_benchmark_suite(
        source_artifact=Path("examples/runs/m2_capture_boundaries.rpk"),
        iterations=1,
    )
    baseline = json.loads(json.dumps({"benchmark": suite.to_dict()}))
    result = evaluate_benchmark_slowdown_gate(
        suite,
        baseline,
        threshold_percent=1000.0,
    )
    assert result.status == "within_threshold"
