"""Bundle export helpers with redaction profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from replaypack.artifact.exceptions import ArtifactRedactionProfileError
from replaypack.artifact.io import read_artifact, write_artifact
from replaypack.capture.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy, redact_payload
from replaypack.core.models import Run, Step

RedactionProfile = Literal["default", "none"]

NONE_REDACTION_POLICY = RedactionPolicy(version="1.0-none", enabled=False)


def resolve_redaction_policy(profile: str) -> tuple[RedactionProfile, RedactionPolicy]:
    normalized = profile.strip().lower()
    if normalized == "default":
        return "default", DEFAULT_REDACTION_POLICY
    if normalized == "none":
        return "none", NONE_REDACTION_POLICY
    raise ArtifactRedactionProfileError(
        "Unknown redaction profile "
        f"'{profile}'. Supported profiles: default, none"
    )


def redact_run_for_bundle(run: Run, *, policy: RedactionPolicy) -> Run:
    """Apply redaction policy to run fields and step payloads."""
    redacted_steps: list[Step] = []
    for step in run.steps:
        redacted_steps.append(
            Step(
                id=step.id,
                type=step.type,
                input=redact_payload(step.input, policy=policy),
                output=redact_payload(step.output, policy=policy),
                metadata=redact_payload(step.metadata, policy=policy),
            ).with_hash()
        )

    return Run(
        id=run.id,
        timestamp=run.timestamp,
        environment_fingerprint=redact_payload(run.environment_fingerprint, policy=policy),
        runtime_versions=redact_payload(run.runtime_versions, policy=policy),
        steps=redacted_steps,
    )


def write_bundle_artifact(
    source_artifact_path: str | Path,
    out_path: str | Path,
    *,
    redaction_profile: str = "default",
) -> dict:
    """Write a redacted bundle artifact from an input artifact path."""
    source_run = read_artifact(source_artifact_path)
    profile_name, policy = resolve_redaction_policy(redaction_profile)
    bundled_run = redact_run_for_bundle(source_run, policy=policy)

    return write_artifact(
        bundled_run,
        out_path,
        metadata={
            "bundle": True,
            "source_run_id": source_run.id,
            "redaction_profile": profile_name,
            "redaction_policy_version": policy.version,
        },
    )
