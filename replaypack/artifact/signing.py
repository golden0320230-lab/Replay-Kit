"""Artifact HMAC signing and verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Any, Literal

from replaypack.artifact.exceptions import ArtifactSignatureError, ArtifactSigningKeyError
from replaypack.core.canonical import canonical_json

SIGNATURE_ALGORITHM = "hmac-sha256"
SIGNING_KEY_ENV_VAR = "REPLAYKIT_SIGNING_KEY"
SIGNING_KEY_ID_ENV_VAR = "REPLAYKIT_SIGNING_KEY_ID"

SignatureStatus = Literal[
    "verified",
    "unsigned_allowed",
    "missing_signature",
    "missing_key",
    "invalid_signature",
    "unsupported_algorithm",
]


@dataclass(slots=True, frozen=True)
class SignatureVerificationResult:
    """Signature verification result payload."""

    valid: bool
    status: SignatureStatus
    message: str
    algorithm: str | None
    key_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "message": self.message,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
        }

def signature_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    """Canonical payload for HMAC signing (excludes signature field)."""
    return {
        "version": artifact["version"],
        "metadata": artifact["metadata"],
        "payload": artifact["payload"],
        "checksum": artifact["checksum"],
    }


def compute_artifact_hmac(artifact: dict[str, Any], signing_key: str) -> str:
    """Compute HMAC digest for artifact payload."""
    key = _normalize_signing_key(signing_key)
    payload = canonical_json(signature_payload(artifact)).encode("utf-8")
    digest = hmac.new(key, payload, "sha256").hexdigest()
    return f"{SIGNATURE_ALGORITHM}:{digest}"


def sign_artifact_envelope(
    artifact: dict[str, Any],
    *,
    signing_key: str,
    key_id: str = "default",
) -> dict[str, Any]:
    """Attach signature field to an artifact envelope."""
    digest = compute_artifact_hmac(artifact, signing_key)
    signed = dict(artifact)
    signed["signature"] = {
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "value": digest,
    }
    return signed


def verify_artifact_signature(
    artifact: dict[str, Any],
    *,
    signing_key: str | None,
    require_signature: bool = True,
) -> SignatureVerificationResult:
    """Verify artifact signature and return structured status."""
    signature = artifact.get("signature")
    if not isinstance(signature, dict):
        if require_signature:
            return SignatureVerificationResult(
                valid=False,
                status="missing_signature",
                message="Artifact is unsigned.",
                algorithm=None,
                key_id=None,
            )
        return SignatureVerificationResult(
            valid=True,
            status="unsigned_allowed",
            message="Artifact is unsigned and unsigned artifacts are allowed.",
            algorithm=None,
            key_id=None,
        )

    algorithm = str(signature.get("algorithm", "")).strip()
    key_id = str(signature.get("key_id", "")).strip() or None
    value = str(signature.get("value", "")).strip()

    if algorithm != SIGNATURE_ALGORITHM:
        return SignatureVerificationResult(
            valid=False,
            status="unsupported_algorithm",
            message=f"Unsupported signature algorithm: {algorithm}",
            algorithm=algorithm or None,
            key_id=key_id,
        )

    if not signing_key:
        return SignatureVerificationResult(
            valid=False,
            status="missing_key",
            message=(
                "Signature key is required for verification. "
                f"Set {SIGNING_KEY_ENV_VAR} or pass --signing-key."
            ),
            algorithm=algorithm,
            key_id=key_id,
        )

    try:
        expected = compute_artifact_hmac(artifact, signing_key)
    except ArtifactSigningKeyError as error:
        raise ArtifactSignatureError(str(error)) from error

    if not hmac.compare_digest(value, expected):
        return SignatureVerificationResult(
            valid=False,
            status="invalid_signature",
            message="Artifact signature mismatch.",
            algorithm=algorithm,
            key_id=key_id,
        )

    return SignatureVerificationResult(
        valid=True,
        status="verified",
        message="Artifact signature verified.",
        algorithm=algorithm,
        key_id=key_id,
    )


def _normalize_signing_key(signing_key: str) -> bytes:
    if not isinstance(signing_key, str):
        raise ArtifactSigningKeyError("Signing key must be a string.")
    stripped = signing_key.strip()
    if not stripped:
        raise ArtifactSigningKeyError("Signing key cannot be empty.")
    return stripped.encode("utf-8")
