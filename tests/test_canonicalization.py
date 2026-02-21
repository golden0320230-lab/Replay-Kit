from replaypack.core.canonical import canonical_json, canonicalize


def test_equivalent_inputs_canonicalize_to_same_json() -> None:
    left = {
        "timestamp": "2026-02-21T14:00:00Z",
        "file_path": "C:\\Users\\alice\\runs\\session\\artifact.rpk",
        "prompt": "line one\r\nline two",
        "metadata": {
            "labels": ["beta", "alpha"],
            "unknown": {"b": 2, "a": 1},
        },
    }

    right = {
        "metadata": {
            "unknown": {"a": 1, "b": 2},
            "labels": ["alpha", "beta"],
        },
        "prompt": "line one\nline two",
        "file_path": "/c/Users/alice/runs/session/artifact.rpk",
        "timestamp": "2026-02-21T09:00:00-05:00",
    }

    assert canonical_json(left) == canonical_json(right)


def test_unknown_fields_are_preserved() -> None:
    payload = {
        "known": "value",
        "nested": {
            "custom_field": "kept",
        },
    }

    canonical = canonicalize(payload)

    assert canonical["known"] == "value"
    assert canonical["nested"]["custom_field"] == "kept"


def test_volatile_fields_are_removed_only_when_enabled() -> None:
    metadata = {
        "provider": "openai",
        "duration_ms": 123,
        "nested": {
            "trace_id": "trace-1",
            "status": "ok",
        },
    }

    preserved = canonicalize(metadata, strip_volatile=False)
    stripped = canonicalize(metadata, strip_volatile=True)

    assert "duration_ms" in preserved
    assert "duration_ms" not in stripped
    assert "trace_id" in preserved["nested"]
    assert "trace_id" not in stripped["nested"]
    assert stripped["provider"] == "openai"
    assert stripped["nested"]["status"] == "ok"
