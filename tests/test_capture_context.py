import asyncio
import threading

import pytest

from replaypack.capture import (
    capture_model_call,
    capture_run,
    capture_tool_call,
    get_current_context,
)


@pytest.fixture(autouse=True)
def _assert_no_context_leak() -> None:
    assert get_current_context() is None
    yield
    assert get_current_context() is None


def test_nested_capture_run_uses_stack_semantics() -> None:
    inner_run = None

    with capture_run(
        run_id="run-outer-001",
        timestamp="2026-02-21T16:00:00Z",
    ) as outer_context:
        assert get_current_context() is outer_context

        capture_model_call(
            "gpt-4o-mini",
            {"prompt": "outer-1"},
            lambda: {"content": "outer-1"},
        )

        with capture_run(
            run_id="run-inner-001",
            timestamp="2026-02-21T16:01:00Z",
        ) as inner_context:
            assert get_current_context() is inner_context
            capture_model_call(
                "gpt-4o-mini",
                {"prompt": "inner-1"},
                lambda: {"content": "inner-1"},
            )
            inner_run = inner_context.to_run()

        assert get_current_context() is outer_context
        capture_model_call(
            "gpt-4o-mini",
            {"prompt": "outer-2"},
            lambda: {"content": "outer-2"},
        )
        outer_run = outer_context.to_run()

    assert inner_run is not None
    assert outer_run.id == "run-outer-001"
    assert inner_run.id == "run-inner-001"

    assert [step.id for step in outer_run.steps] == [
        "step-000001",
        "step-000002",
        "step-000003",
        "step-000004",
    ]
    assert [step.id for step in inner_run.steps] == [
        "step-000001",
        "step-000002",
    ]


def test_capture_run_resets_context_after_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with capture_run(
            run_id="run-error-001",
            timestamp="2026-02-21T16:02:00Z",
        ):
            raise RuntimeError("boom")

    assert get_current_context() is None


def test_async_capture_context_isolation() -> None:
    async def worker(run_id: str, prompt: str):
        with capture_run(
            run_id=run_id,
            timestamp="2026-02-21T16:03:00Z",
        ) as context:
            capture_model_call(
                "gpt-4o-mini",
                {"prompt": prompt},
                lambda: {"content": prompt},
            )
            await asyncio.sleep(0)
            capture_model_call(
                "gpt-4o-mini",
                {"prompt": f"{prompt}-2"},
                lambda: {"content": f"{prompt}-2"},
            )
            return context.to_run()

    async def run_workers():
        return await asyncio.gather(
            worker("run-async-001", "alpha"),
            worker("run-async-002", "beta"),
        )

    run_a, run_b = asyncio.run(run_workers())

    assert run_a.id == "run-async-001"
    assert run_b.id == "run-async-002"
    assert len(run_a.steps) == 4
    assert len(run_b.steps) == 4

    prompts_a = [
        step.input["input"]["prompt"]
        for step in run_a.steps
        if step.type == "model.request"
    ]
    prompts_b = [
        step.input["input"]["prompt"]
        for step in run_b.steps
        if step.type == "model.request"
    ]
    assert prompts_a == ["alpha", "alpha-2"]
    assert prompts_b == ["beta", "beta-2"]


def test_thread_does_not_inherit_parent_capture_context() -> None:
    thread_observations: list[tuple[str, object | None]] = []

    with capture_run(
        run_id="run-thread-parent-001",
        timestamp="2026-02-21T16:04:00Z",
    ) as context:
        capture_model_call(
            "gpt-4o-mini",
            {"prompt": "main-thread"},
            lambda: {"content": "main-thread"},
        )

        def worker() -> None:
            output = capture_model_call(
                "gpt-4o-mini",
                {"prompt": "worker-thread"},
                lambda: {"content": "worker-thread"},
            )
            thread_observations.append((output["content"], get_current_context()))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)

        run = context.to_run()

    assert not thread.is_alive()
    assert thread_observations == [("worker-thread", None)]
    # Worker ran without inherited context, so only main-thread model call is captured.
    assert len(run.steps) == 2
    assert run.steps[0].input["input"]["prompt"] == "main-thread"


def test_shared_context_records_monotonic_ids_under_threads() -> None:
    workers = 8
    iterations = 40
    start_barrier = threading.Barrier(workers)
    failures: list[Exception] = []
    failures_lock = threading.Lock()

    with capture_run(
        run_id="run-thread-shared-001",
        timestamp="2026-02-21T16:05:00Z",
    ) as context:
        def worker(worker_id: int) -> None:
            try:
                start_barrier.wait(timeout=5)
                for iteration in range(iterations):
                    capture_tool_call(
                        tool_name="thread-worker",
                        args=(worker_id, iteration),
                        kwargs={},
                        invoke=lambda w=worker_id, i=iteration: {"worker": w, "i": i},
                        context=context,
                        metadata={"worker": worker_id},
                    )
            except Exception as error:  # pragma: no cover - defensive branch
                with failures_lock:
                    failures.append(error)

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        run = context.to_run()

    assert not failures
    assert all(not thread.is_alive() for thread in threads)

    expected_steps = workers * iterations * 2
    assert len(run.steps) == expected_steps
    assert [step.id for step in run.steps] == [
        f"step-{idx:06d}" for idx in range(1, expected_steps + 1)
    ]
    assert sum(step.type == "tool.request" for step in run.steps) == workers * iterations
    assert sum(step.type == "tool.response" for step in run.steps) == workers * iterations
