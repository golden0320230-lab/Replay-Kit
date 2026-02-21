"""Stable hashing for ReplayKit steps."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from replaypack.core.canonical import canonical_json


@dataclass(frozen=True, slots=True)
class StepHashSummary:
    """Hash details exposed for debugging and diagnostics."""

    algorithm: str
    scope: str
    digest: str


def compute_step_hash(
    step_type: str,
    input_value: Any,
    output_value: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic hash for a step.

    Volatile metadata fields are removed before hashing.
    """
    hash_input = {
        "type": step_type,
        "input": input_value,
        "output": output_value,
        "metadata": metadata or {},
    }
    payload = canonical_json(hash_input, strip_volatile=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_step_hash_summary(
    step_type: str,
    input_value: Any,
    output_value: Any,
    metadata: dict[str, Any] | None = None,
) -> StepHashSummary:
    digest = compute_step_hash(step_type, input_value, output_value, metadata)
    return StepHashSummary(
        algorithm="sha256",
        scope="type+input+output+metadata(strip_volatile)",
        digest=digest,
    )
