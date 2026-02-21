from replaypack.core.hashing import compute_step_hash, compute_step_hash_summary


def test_hash_is_stable_when_only_volatile_metadata_changes() -> None:
    base_hash = compute_step_hash(
        "model.response",
        {"prompt": "hello"},
        {"content": "world"},
        {"provider": "openai", "duration_ms": 10},
    )

    same_hash = compute_step_hash(
        "model.response",
        {"prompt": "hello"},
        {"content": "world"},
        {"provider": "openai", "duration_ms": 999},
    )

    assert base_hash == same_hash


def test_hash_changes_for_meaningful_deltas() -> None:
    baseline = compute_step_hash(
        "model.response",
        {"prompt": "hello"},
        {"content": "world"},
        {"provider": "openai"},
    )

    variants = [
        compute_step_hash(
            "model.request",
            {"prompt": "hello"},
            {"content": "world"},
            {"provider": "openai"},
        ),
        compute_step_hash(
            "model.response",
            {"prompt": "goodbye"},
            {"content": "world"},
            {"provider": "openai"},
        ),
        compute_step_hash(
            "model.response",
            {"prompt": "hello"},
            {"content": "changed"},
            {"provider": "openai"},
        ),
        compute_step_hash(
            "model.response",
            {"prompt": "hello"},
            {"content": "world"},
            {"provider": "anthropic"},
        ),
    ]

    for variant in variants:
        assert variant != baseline


def test_hash_summary_includes_scope() -> None:
    summary = compute_step_hash_summary(
        "tool.response",
        {"name": "search"},
        {"result": "ok"},
        {"latency_ms": 5},
    )

    assert summary.algorithm == "sha256"
    assert "metadata(strip_volatile)" in summary.scope
    assert summary.digest.startswith("sha256:")
