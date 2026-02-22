import json
from pathlib import Path

import pytest

from replaypack.artifact import (
    ArtifactSigningKeyError,
    SignatureVerificationResult,
    compute_artifact_checksum,
    read_artifact,
    read_artifact_envelope,
    verify_artifact_signature,
    write_artifact,
)
from replaypack.core.models import Run, Step


def _run_for_signing() -> Run:
    return Run(
        id="run-sign-001",
        timestamp="2026-02-22T16:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.0", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-001",
                type="model.request",
                input={"prompt": "hello"},
                output={"status": "sent"},
                metadata={"provider": "openai"},
            ),
            Step(
                id="step-002",
                type="model.response",
                input={"request_id": "req-sign-1"},
                output={"content": "hi"},
                metadata={"provider": "openai"},
            ),
        ],
    )


def test_signed_artifact_verifies_and_reads(tmp_path: Path) -> None:
    path = tmp_path / "signed.rpk"
    write_artifact(_run_for_signing(), path, sign=True, signing_key="test-signing-key")

    envelope = read_artifact_envelope(path)
    verify_result: SignatureVerificationResult = verify_artifact_signature(
        envelope,
        signing_key="test-signing-key",
    )

    assert verify_result.valid is True
    assert verify_result.status == "verified"

    loaded_run = read_artifact(path)
    assert loaded_run.id == "run-sign-001"
    assert len(loaded_run.steps) == 2


def test_verification_fails_for_tampered_payload_even_if_checksum_recomputed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "signed.rpk"
    write_artifact(_run_for_signing(), path, sign=True, signing_key="test-signing-key")

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["run"]["steps"][1]["output"]["content"] = "tampered"
    raw["checksum"] = compute_artifact_checksum(
        {
            "version": raw["version"],
            "metadata": raw["metadata"],
            "payload": raw["payload"],
        }
    )
    path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    envelope = read_artifact_envelope(path)
    verify_result = verify_artifact_signature(
        envelope,
        signing_key="test-signing-key",
    )

    assert verify_result.valid is False
    assert verify_result.status == "invalid_signature"


def test_verification_fails_when_signature_missing() -> None:
    envelope = {
        "version": "1.0",
        "metadata": {"run_id": "run-1", "created_at": "2026-02-22T16:00:00Z"},
        "payload": {
            "run": {
                "id": "run-1",
                "timestamp": "2026-02-22T16:00:00Z",
                "environment_fingerprint": {},
                "runtime_versions": {},
                "steps": [],
            }
        },
        "checksum": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    }

    result = verify_artifact_signature(envelope, signing_key="k")
    assert result.valid is False
    assert result.status == "missing_signature"


def test_write_artifact_sign_requires_key(tmp_path: Path) -> None:
    path = tmp_path / "missing-key.rpk"
    with pytest.raises(ArtifactSigningKeyError, match="Signing requested"):
        write_artifact(_run_for_signing(), path, sign=True, signing_key=None)
