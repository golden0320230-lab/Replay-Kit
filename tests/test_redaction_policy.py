import json
from pathlib import Path

import pytest

from replaypack.capture.redaction import (
    RedactionPolicyConfigError,
    build_redaction_policy,
    load_redaction_policy_from_file,
    redact_payload,
    redaction_policy_from_config,
)


def test_build_redaction_policy_masks_custom_fields_and_patterns() -> None:
    policy = build_redaction_policy(
        version="team-policy-1",
        extra_sensitive_field_names=("session_id",),
        extra_secret_value_patterns=(r"\bghp_[A-Za-z0-9]{20,}\b",),
        extra_sensitive_path_patterns=(r"^/metadata/internal_trace$",),
    )

    payload = {
        "session_id": "session-plain-text",
        "note": "token=ghp_1234567890abcdefghijklmn",
        "metadata": {"internal_trace": "trace-123"},
    }
    redacted = redact_payload(payload, policy=policy)

    assert redacted["session_id"] == "[REDACTED]"
    assert redacted["note"] == "token=[REDACTED]"
    assert redacted["metadata"]["internal_trace"] == "[REDACTED]"


def test_safe_field_cannot_override_sensitive_field() -> None:
    policy = build_redaction_policy(extra_safe_field_names=("token",))
    redacted = redact_payload({"token": "sk-plain-secret-1234567890"}, policy=policy)
    assert redacted["token"] == "[REDACTED]"


def test_redaction_policy_from_config_rejects_unknown_keys() -> None:
    with pytest.raises(RedactionPolicyConfigError, match="Unsupported redaction config keys"):
        redaction_policy_from_config({"unknown_key": True})


def test_load_redaction_policy_from_file(tmp_path: Path) -> None:
    config_path = tmp_path / "redaction.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "team-policy-2",
                "extra_sensitive_field_names": ["request_id"],
            }
        ),
        encoding="utf-8",
    )

    policy = load_redaction_policy_from_file(config_path)
    redacted = redact_payload({"request_id": "rq-123"}, policy=policy)

    assert policy.version == "team-policy-2"
    assert redacted["request_id"] == "[REDACTED]"


def test_default_redaction_masks_authorization_and_secret_payload_keys() -> None:
    redacted = redact_payload(
        {
            "Authorization": "Bearer sk-verysecret0000000000",
            "api_key": "key-123",
            "token": "token-456",
            "secret": "secret-789",
            "password": "pass-000",
            "safe": "visible",
        }
    )
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["secret"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["safe"] == "visible"


def test_default_redaction_masks_common_provider_token_formats() -> None:
    jwt_like = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkFkbWluIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    payload = {
        "google_key": "AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "github_token": "gho_1234567890abcdefghijklmnopqrstuv",
        "jwt": jwt_like,
        "note": "safe",
    }
    redacted = redact_payload(payload)
    assert redacted["google_key"] == "[REDACTED]"
    assert redacted["github_token"] == "[REDACTED]"
    assert redacted["jwt"] == "[REDACTED]"
    assert redacted["note"] == "safe"
