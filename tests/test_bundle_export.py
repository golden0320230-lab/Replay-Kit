import json
from pathlib import Path

import pytest

from replaypack.artifact import (
    ArtifactRedactionProfileError,
    read_artifact,
    write_artifact,
    write_bundle_artifact,
)
from replaypack.capture import build_redaction_policy
from replaypack.core.models import Run, Step
from replaypack.replay import ReplayConfig, write_replay_stub_artifact


def _build_secret_run() -> Run:
    return Run(
        id="run-bundle-secret-001",
        timestamp="2026-02-21T20:10:00Z",
        environment_fingerprint={
            "os": "macOS",
            "owner_email": "dev@example.com",
        },
        runtime_versions={
            "python": "3.12.1",
            "replaykit": "0.1.0",
        },
        steps=[
            Step(
                id="step-001",
                type="tool.request",
                input={
                    "headers": {
                        "Authorization": "Bearer sk-secret-auth-1234567890",
                        "X-Api-Key": "AKIAIOSFODNN7EXAMPLE",
                    },
                    "body": {
                        "token": "sk-secret-body-1234567890",
                        "email": "customer@example.com",
                    },
                },
                output={"status": "sent"},
                metadata={"provider": "test", "secret": "hidden"},
            ),
            Step(
                id="step-002",
                type="tool.response",
                input={"ok": True},
                output={
                    "headers": {"Set-Cookie": "session=abcd"},
                    "body": {"email": "customer@example.com"},
                },
                metadata={"provider": "test"},
            ),
        ],
    )


def test_bundle_default_profile_redacts_sensitive_values(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    bundle = tmp_path / "incident.bundle"

    write_artifact(_build_secret_run(), source)
    envelope = write_bundle_artifact(source, bundle, redaction_profile="default")
    bundled_run = read_artifact(bundle)

    assert envelope["metadata"]["bundle"] is True
    assert envelope["metadata"]["redaction_profile"] == "default"

    step0 = bundled_run.steps[0]
    assert step0.input["headers"]["Authorization"] == "[REDACTED]"
    assert step0.input["headers"]["X-Api-Key"] == "[REDACTED]"
    assert step0.input["body"]["token"] == "[REDACTED]"
    assert step0.input["body"]["email"] == "[REDACTED]"
    assert step0.metadata["secret"] == "[REDACTED]"


def test_bundle_none_profile_keeps_original_values(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    bundle = tmp_path / "raw.bundle"

    write_artifact(_build_secret_run(), source)
    write_bundle_artifact(source, bundle, redaction_profile="none")

    bundled_run = read_artifact(bundle)
    step0 = bundled_run.steps[0]

    assert step0.input["headers"]["Authorization"].startswith("Bearer sk-")
    assert step0.input["body"]["email"] == "customer@example.com"
    assert step0.metadata["secret"] == "hidden"


def test_bundle_invalid_profile_fails() -> None:
    with pytest.raises(ArtifactRedactionProfileError, match="Unknown redaction profile"):
        write_bundle_artifact(
            "examples/runs/m2_capture_boundaries.rpk",
            "runs/unused.bundle",
            redaction_profile="invalid",
        )


def test_bundle_custom_policy_applies_configured_rules(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    bundle = tmp_path / "custom.bundle"
    policy = build_redaction_policy(
        version="bundle-custom-1",
        extra_sensitive_field_names=("provider",),
    )

    write_artifact(_build_secret_run(), source)
    envelope = write_bundle_artifact(
        source,
        bundle,
        redaction_policy=policy,
        redaction_profile_label="custom",
    )

    bundled_run = read_artifact(bundle)
    assert envelope["metadata"]["redaction_profile"] == "custom"
    assert bundled_run.steps[0].metadata["provider"] == "[REDACTED]"


def test_bundle_is_replay_safe_after_redaction(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    bundle = tmp_path / "incident.bundle"
    replayed = tmp_path / "replayed.rpk"

    write_artifact(_build_secret_run(), source)
    write_bundle_artifact(source, bundle, redaction_profile="default")

    bundled_run = read_artifact(bundle)
    write_replay_stub_artifact(
        bundled_run,
        str(replayed),
        config=ReplayConfig(seed=2, fixed_clock="2026-02-21T20:30:00Z"),
    )

    replayed_run = read_artifact(replayed)
    assert replayed_run.runtime_versions["replay_mode"] == "stub"
    assert len(replayed_run.steps) == len(bundled_run.steps)
    assert replayed_run.steps[0].input["body"]["token"] == "[REDACTED]"


def test_m5_bundle_fixture_metadata_present() -> None:
    fixture = Path("examples/runs/m5_bundle_default.bundle")
    raw = json.loads(fixture.read_text(encoding="utf-8"))

    assert raw["metadata"]["bundle"] is True
    assert raw["metadata"]["redaction_profile"] == "default"
