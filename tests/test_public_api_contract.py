import inspect
from pathlib import Path

import replaykit
from replaypack.artifact import read_artifact


def test_public_api_symbol_list_is_explicit_and_stable() -> None:
    assert replaykit.__all__ == [
        "__version__",
        "ReplayMode",
        "CaptureInterceptor",
        "AssertionResult",
        "RunDiffResult",
        "SnapshotWorkflowResult",
        "tool",
        "record",
        "replay",
        "diff",
        "assert_run",
        "bundle",
        "snapshot_assert",
    ]


def test_public_api_function_signatures_and_annotations() -> None:
    expected_parameter_order = {
        "record": (
            "path",
            "mode",
            "redaction",
            "redaction_policy",
            "intercept",
            "run_id",
            "timestamp",
        ),
        "replay": (
            "path",
            "out",
            "mode",
            "seed",
            "fixed_clock",
            "rerun_from",
            "rerun_step_types",
            "rerun_step_ids",
        ),
        "diff": ("left", "right", "first_only", "max_changes_per_step", "redaction_policy"),
        "assert_run": ("baseline", "candidate", "strict", "max_changes_per_step"),
        "bundle": ("path", "out", "redaction_profile", "redaction_policy"),
        "snapshot_assert": (
            "name",
            "candidate",
            "snapshots_dir",
            "update",
            "strict",
            "max_changes_per_step",
        ),
    }

    for name, parameters in expected_parameter_order.items():
        function = getattr(replaykit, name)
        signature = inspect.signature(function)
        assert tuple(signature.parameters.keys()) == parameters
        assert "return" in function.__annotations__
        assert function.__doc__ is not None
        assert function.__doc__.strip() != ""

        for index, parameter in enumerate(signature.parameters.values()):
            if index == 0 and name not in {"diff", "assert_run", "snapshot_assert"}:
                assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                continue
            if name == "diff" and index < 2:
                assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                continue
            if name == "assert_run" and index < 2:
                assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                continue
            if name == "snapshot_assert" and index < 2:
                assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
                continue
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_core_workflow_works_via_public_api_only(tmp_path: Path) -> None:
    source_path = tmp_path / "public-api-source.rpk"
    replay_path = tmp_path / "public-api-replay.rpk"
    bundle_path = tmp_path / "public-api.bundle"
    snapshots_dir = tmp_path / "snapshots"

    recorded = replaykit.record(source_path)
    assert source_path.exists()
    assert recorded["metadata"]["run_id"] == "run-demo-001"

    replayed = replaykit.replay(
        source_path,
        out=replay_path,
        mode="stub",
        seed=123,
        fixed_clock="2026-02-22T00:00:00Z",
    )
    assert replay_path.exists()
    assert replayed["metadata"]["run_id"].startswith("replay-")

    diff_result = replaykit.diff(source_path, replay_path, first_only=True)
    assert diff_result.total_left_steps > 0
    assert diff_result.total_right_steps > 0

    assertion = replaykit.assert_run(source_path, source_path, strict=True)
    assert assertion.passed is True
    assert assertion.exit_code == 0

    bundle_result = replaykit.bundle(source_path, out=bundle_path)
    assert bundle_path.exists()
    assert bundle_result["metadata"]["bundle"] is True

    update_result = replaykit.snapshot_assert(
        "public-api-flow",
        source_path,
        snapshots_dir=snapshots_dir,
        update=True,
    )
    assert update_result.status == "updated"

    assert_result = replaykit.snapshot_assert(
        "public-api-flow",
        source_path,
        snapshots_dir=snapshots_dir,
    )
    assert assert_result.status == "pass"
    assert assert_result.assertion is not None
    assert assert_result.assertion.passed is True


def test_record_context_manager_mode_runs_without_cli(tmp_path: Path) -> None:
    out_path = tmp_path / "context-record.rpk"

    @replaykit.tool(name="contract.echo")
    def echo(value: str) -> dict[str, str]:
        return {"echo": value}

    with replaykit.record(
        out_path,
        intercept=("requests", "httpx"),
        run_id="run-contract-context",
        timestamp="2026-02-22T20:00:00Z",
    ):
        echo("hello")

    assert out_path.exists()
    run = read_artifact(out_path)
    assert run.id == "run-contract-context"
    assert [step.type for step in run.steps] == ["tool.request", "tool.response"]


def test_public_api_policy_doc_includes_semver_rules() -> None:
    policy = Path("docs/PUBLIC_API.md").read_text(encoding="utf-8")
    normalized = policy.lower()
    assert "stability policy" in normalized
    assert "semver" in normalized
    assert "major version bump" in normalized
    assert "replaykit.__all__" in policy
