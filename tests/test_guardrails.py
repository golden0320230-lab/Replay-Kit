from replaypack.core.models import Run, Step
from replaypack.diff import diff_runs
from replaypack.guardrails import (
    detect_diff_nondeterminism,
    detect_run_nondeterminism,
    guardrail_payload,
    normalize_guardrail_mode,
)


def _run_with_indicator(
    *,
    run_id: str,
    random_usage: bool = False,
    random_seed: str | None = None,
    time_usage: bool = False,
    fixed_clock: str | None = None,
) -> Run:
    runtime_versions = {"python": "3.12.0", "replaykit": "0.1.0"}
    if random_usage:
        runtime_versions["uses_random"] = "true"
    if random_seed is not None:
        runtime_versions["random_seed"] = random_seed
    if time_usage:
        runtime_versions["uses_time"] = "true"
    if fixed_clock is not None:
        runtime_versions["fixed_clock"] = fixed_clock

    return Run(
        id=run_id,
        timestamp="2026-02-22T18:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions=runtime_versions,
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ).with_hash(),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "req-001"},
                output={"content": "hi"},
                metadata={"provider": "openai"},
            ).with_hash(),
        ],
    )


def test_detect_run_nondeterminism_flags_unseeded_random_and_unstable_time() -> None:
    run = _run_with_indicator(
        run_id="run-guardrails-001",
        random_usage=True,
        time_usage=True,
    )

    findings = detect_run_nondeterminism(run, run_label="source")
    kinds = {finding.kind for finding in findings}

    assert "random_unseeded" in kinds
    assert "time_unstable" in kinds


def test_detect_run_nondeterminism_clear_when_seed_and_fixed_clock_present() -> None:
    run = _run_with_indicator(
        run_id="run-guardrails-002",
        random_usage=True,
        random_seed="42",
        time_usage=True,
        fixed_clock="2026-01-01T00:00:00Z",
    )

    findings = detect_run_nondeterminism(run, run_label="source")
    assert findings == []


def test_detect_diff_nondeterminism_flags_volatile_tokens() -> None:
    left = _run_with_indicator(run_id="run-left")
    right = _run_with_indicator(run_id="run-right")
    right.steps[1].input["request_id"] = "req-999"
    right.steps[1].output["timestamp"] = "2026-02-22T18:05:00Z"
    right.steps[1] = right.steps[1].with_hash()

    diff = diff_runs(left, right, stop_at_first_divergence=False, max_changes_per_step=16)
    findings = detect_diff_nondeterminism(diff)
    kinds = {finding.kind for finding in findings}

    assert "random_unseeded" in kinds
    assert "time_unstable" in kinds


def test_guardrail_payload_and_mode_validation() -> None:
    assert normalize_guardrail_mode("OFF") == "off"
    assert normalize_guardrail_mode("warn") == "warn"
    assert normalize_guardrail_mode("fail") == "fail"

    payload = guardrail_payload(mode="warn", findings=[])
    assert payload["status"] == "clear"
    assert payload["count"] == 0
