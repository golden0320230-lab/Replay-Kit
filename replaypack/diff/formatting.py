"""CLI-friendly rendering for diff results."""

from __future__ import annotations

from replaypack.diff.models import RunDiffResult


def render_diff_summary(diff: RunDiffResult) -> str:
    summary = diff.summary()
    return (
        f"left={diff.left_run_id} right={diff.right_run_id} "
        f"identical={summary['identical']} changed={summary['changed']} "
        f"missing_left={summary['missing_left']} missing_right={summary['missing_right']}"
    )


def render_first_divergence(diff: RunDiffResult, *, max_changes: int = 8) -> str:
    first = diff.first_divergence
    if first is None:
        return "no divergence detected"

    lines: list[str] = []
    lines.append(f"first divergence: step {first.index} ({first.status})")
    lines.append(
        "left_step="
        f"{first.left_step_id or '<none>'}:{first.left_type or '<none>'} "
        "right_step="
        f"{first.right_step_id or '<none>'}:{first.right_type or '<none>'}"
    )

    if first.context:
        lines.append("context:")
        for key in sorted(first.context.keys()):
            lines.append(f"  {key}={first.context[key]}")

    if first.changes:
        lines.append("changes:")
        for change in first.changes[:max_changes]:
            lines.append(f"  {change.path}: {change.left} -> {change.right}")
        if first.truncated_changes or len(first.changes) > max_changes:
            lines.append("  ... additional changes omitted")

    return "\n".join(lines)
