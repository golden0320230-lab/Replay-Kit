"""O(n) run diff engine with first-divergence detection."""

from __future__ import annotations

from typing import Any

from replaypack.core.models import Run, Step
from replaypack.diff.models import RunDiffResult, StepDiff, ValueChange
from replaypack.plugins import DiffEndEvent, DiffStartEvent, get_active_plugin_manager

_MISSING = object()


def diff_runs(
    left: Run,
    right: Run,
    *,
    stop_at_first_divergence: bool = False,
    max_changes_per_step: int = 32,
) -> RunDiffResult:
    """Diff two runs in O(n) step count.

    Steps are compared by ordered position.
    """
    plugin_manager = get_active_plugin_manager()
    plugin_manager.on_diff_start(
        DiffStartEvent(
            left_run_id=left.id,
            right_run_id=right.id,
            stop_at_first_divergence=stop_at_first_divergence,
            max_changes_per_step=max_changes_per_step,
            total_left_steps=len(left.steps),
            total_right_steps=len(right.steps),
        )
    )

    left_steps = left.steps
    right_steps = right.steps
    max_len = max(len(left_steps), len(right_steps))

    step_diffs: list[StepDiff] = []

    try:
        for idx in range(max_len):
            left_step = left_steps[idx] if idx < len(left_steps) else None
            right_step = right_steps[idx] if idx < len(right_steps) else None

            step_diff = _diff_step(
                index=idx + 1,
                left_step=left_step,
                right_step=right_step,
                max_changes=max_changes_per_step,
            )
            step_diffs.append(step_diff)

            if stop_at_first_divergence and step_diff.status != "identical":
                break

        result = RunDiffResult(
            left_run_id=left.id,
            right_run_id=right.id,
            total_left_steps=len(left_steps),
            total_right_steps=len(right_steps),
            step_diffs=step_diffs,
        )
    except Exception as error:
        plugin_manager.on_diff_end(
            DiffEndEvent(
                left_run_id=left.id,
                right_run_id=right.id,
                status="error",
                error_type=error.__class__.__name__,
                error_message=str(error),
            )
        )
        raise

    first = result.first_divergence
    plugin_manager.on_diff_end(
        DiffEndEvent(
            left_run_id=left.id,
            right_run_id=right.id,
            status="ok",
            identical=result.identical,
            first_divergence_index=first.index if first is not None else None,
            summary=result.summary(),
        )
    )
    return result


def _diff_step(
    *,
    index: int,
    left_step: Step | None,
    right_step: Step | None,
    max_changes: int,
) -> StepDiff:
    if left_step is None:
        return StepDiff(
            index=index,
            status="missing_left",
            left_step_id=None,
            right_step_id=right_step.id,
            left_type=None,
            right_type=right_step.type,
            changes=[
                ValueChange(
                    path="/step",
                    left="<MISSING>",
                    right=right_step.to_dict(),
                )
            ],
        )

    if right_step is None:
        return StepDiff(
            index=index,
            status="missing_right",
            left_step_id=left_step.id,
            right_step_id=None,
            left_type=left_step.type,
            right_type=None,
            changes=[
                ValueChange(
                    path="/step",
                    left=left_step.to_dict(),
                    right="<MISSING>",
                )
            ],
        )

    if _steps_equivalent(left_step, right_step):
        return StepDiff(
            index=index,
            status="identical",
            left_step_id=left_step.id,
            right_step_id=right_step.id,
            left_type=left_step.type,
            right_type=right_step.type,
            context=_extract_context(left_step, right_step),
        )

    changes: list[ValueChange] = []
    truncated = False

    if left_step.type != right_step.type:
        changes.append(ValueChange(path="/type", left=left_step.type, right=right_step.type))

    if (left_step.hash or "") != (right_step.hash or ""):
        changes.append(
            ValueChange(
                path="/hash",
                left=left_step.hash or "",
                right=right_step.hash or "",
            )
        )

    truncated |= _collect_value_changes(
        left_step.input,
        right_step.input,
        path="/input",
        out=changes,
        max_changes=max_changes,
    )
    truncated |= _collect_value_changes(
        left_step.output,
        right_step.output,
        path="/output",
        out=changes,
        max_changes=max_changes,
    )
    truncated |= _collect_value_changes(
        left_step.metadata,
        right_step.metadata,
        path="/metadata",
        out=changes,
        max_changes=max_changes,
    )

    return StepDiff(
        index=index,
        status="changed",
        left_step_id=left_step.id,
        right_step_id=right_step.id,
        left_type=left_step.type,
        right_type=right_step.type,
        context=_extract_context(left_step, right_step),
        changes=changes,
        truncated_changes=truncated,
    )


def _steps_equivalent(left: Step, right: Step) -> bool:
    return left.type == right.type and (left.hash or "") == (right.hash or "")


def _extract_context(left: Step, right: Step) -> dict[str, Any]:
    keys = ("model", "provider", "tool", "method", "url", "temperature", "max_tokens")
    context: dict[str, Any] = {}

    for key in keys:
        left_value = _extract_value(left, key)
        right_value = _extract_value(right, key)

        if left_value is None and right_value is None:
            continue

        if left_value == right_value:
            context[key] = left_value
        else:
            context[key] = {"left": left_value, "right": right_value}

    return context


def _extract_value(step: Step, key: str) -> Any:
    if key in step.metadata:
        return step.metadata.get(key)
    if isinstance(step.input, dict) and key in step.input:
        return step.input.get(key)
    if isinstance(step.output, dict) and key in step.output:
        return step.output.get(key)
    return None


def _collect_value_changes(
    left: Any,
    right: Any,
    *,
    path: str,
    out: list[ValueChange],
    max_changes: int,
) -> bool:
    if len(out) >= max_changes:
        return True

    if left is _MISSING or right is _MISSING:
        out.append(
            ValueChange(
                path=path,
                left="<MISSING>" if left is _MISSING else left,
                right="<MISSING>" if right is _MISSING else right,
            )
        )
        return len(out) >= max_changes

    if type(left) is not type(right):
        out.append(ValueChange(path=path, left=left, right=right))
        return len(out) >= max_changes

    if isinstance(left, dict):
        truncated = False
        keys = sorted(set(left.keys()) | set(right.keys()), key=str)
        for key in keys:
            child_path = f"{path}/{_escape_json_pointer(str(key))}"
            left_value = left.get(key, _MISSING)
            right_value = right.get(key, _MISSING)
            truncated |= _collect_value_changes(
                left_value,
                right_value,
                path=child_path,
                out=out,
                max_changes=max_changes,
            )
            if len(out) >= max_changes:
                return True
        return truncated

    if isinstance(left, list):
        truncated = False
        max_len = max(len(left), len(right))
        for idx in range(max_len):
            child_path = f"{path}/{idx}"
            left_value = left[idx] if idx < len(left) else _MISSING
            right_value = right[idx] if idx < len(right) else _MISSING
            truncated |= _collect_value_changes(
                left_value,
                right_value,
                path=child_path,
                out=out,
                max_changes=max_changes,
            )
            if len(out) >= max_changes:
                return True
        return truncated

    if left != right:
        out.append(ValueChange(path=path, left=left, right=right))
        return len(out) >= max_changes

    return False


def _escape_json_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")
