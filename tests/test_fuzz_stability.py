import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import string
from typing import Any

import pytest

from replaypack.artifact import ArtifactError, read_artifact_envelope
from replaypack.core.canonical import canonical_json, canonicalize
from replaypack.core.models import Run, Step
from replaypack.core.types import STEP_TYPES
from replaypack.diff import diff_runs

CORPUS_ROOT = Path(__file__).resolve().parent / "fuzz_corpus"
FUZZ_SEED = 20260222


def _persist_repro(kind: str, payload: dict[str, Any]) -> Path:
    repro_dir = CORPUS_ROOT / "repro"
    repro_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = repro_dir / f"{kind}-{stamp}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _random_key(rng: random.Random) -> str:
    keys = [
        "path",
        "cwd",
        "timestamp",
        "created_at",
        "labels",
        "tags",
        "metadata",
        "value",
        "request_id",
    ]
    if rng.random() < 0.7:
        return rng.choice(keys)
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(3, 10)))


def _random_scalar(rng: random.Random, *, allow_non_finite: bool) -> Any:
    choice = rng.randrange(12)
    if choice == 0:
        return None
    if choice == 1:
        return bool(rng.getrandbits(1))
    if choice == 2:
        return rng.randint(-10_000, 10_000)
    if choice == 3:
        return rng.uniform(-1000, 1000)
    if choice == 4 and allow_non_finite:
        return float("nan")
    if choice == 5 and allow_non_finite:
        return float("inf")
    if choice == 6 and allow_non_finite:
        return -float("inf")
    if choice == 7:
        return "C:\\Users\\alice\\repo\\file.txt"
    if choice == 8:
        return "2026-02-22T14:15:16-05:00"
    return "".join(rng.choice(string.ascii_letters + string.digits + " _-/") for _ in range(rng.randint(0, 24)))


def _random_value(
    rng: random.Random,
    *,
    depth: int,
    allow_non_finite: bool,
) -> Any:
    if depth <= 0:
        return _random_scalar(rng, allow_non_finite=allow_non_finite)

    choice = rng.randrange(5)
    if choice == 0:
        return _random_scalar(rng, allow_non_finite=allow_non_finite)
    if choice in {1, 2}:
        size = rng.randint(0, 5)
        return [
            _random_value(rng, depth=depth - 1, allow_non_finite=allow_non_finite)
            for _ in range(size)
        ]

    size = rng.randint(0, 5)
    value: dict[str, Any] = {}
    for _ in range(size):
        value[_random_key(rng)] = _random_value(
            rng,
            depth=depth - 1,
            allow_non_finite=allow_non_finite,
        )
    return value


def _random_run(rng: random.Random, *, run_id: str, max_steps: int = 8) -> Run:
    step_types = sorted(STEP_TYPES)
    step_count = rng.randint(0, max_steps)
    steps: list[Step] = []
    for idx in range(1, step_count + 1):
        input_payload = _random_value(rng, depth=3, allow_non_finite=False)
        output_payload = _random_value(rng, depth=3, allow_non_finite=False)
        metadata_payload = _random_value(rng, depth=2, allow_non_finite=False)
        if not isinstance(metadata_payload, dict):
            metadata_payload = {"value": metadata_payload}
        step = Step(
            id=f"step-{idx:06d}",
            type=rng.choice(step_types),
            input=input_payload,
            output=output_payload,
            metadata=metadata_payload,
        ).with_hash()
        steps.append(step)

    return Run(
        id=run_id,
        timestamp="2026-02-22T20:00:00Z",
        environment_fingerprint={"os": rng.choice(["macOS", "linux", "windows"])},
        runtime_versions={"python": "3.12.1", "replaykit": "0.1.0"},
        steps=steps,
    )


def test_canonicalization_fuzz_smoke_with_corpus() -> None:
    rng = random.Random(FUZZ_SEED)
    corpus_value = json.loads(
        (CORPUS_ROOT / "canonical" / "path_timestamp_mixed.json").read_text(encoding="utf-8")
    )

    values = [corpus_value]
    values.extend(
        _random_value(rng, depth=4, allow_non_finite=True)
        for _ in range(300)
    )

    for idx, value in enumerate(values):
        try:
            left = canonical_json(value)
            right = canonical_json(copy.deepcopy(value))
            canonicalized = canonicalize(value)
        except ValueError as error:
            assert "NaN and infinity are not supported in canonical JSON" in str(error)
            continue
        except Exception as error:  # pragma: no cover - defensive path
            repro_path = _persist_repro(
                "canonicalization",
                {"index": idx, "error": repr(error), "input": repr(value)},
            )
            pytest.fail(f"unexpected canonicalization fuzz crash: {error} (repro: {repro_path})")

        assert left == right
        assert canonical_json(canonicalized) == left


def test_artifact_parser_fuzz_smoke_with_corpus(tmp_path: Path) -> None:
    rng = random.Random(FUZZ_SEED + 1)
    corpus_paths = [
        CORPUS_ROOT / "parser" / "non_object.json",
        CORPUS_ROOT / "parser" / "missing_required_fields.json",
        Path("examples/runs/minimal_v1.rpk"),
    ]

    for path in corpus_paths:
        try:
            read_artifact_envelope(path)
        except ArtifactError:
            # malformed corpus cases are expected to fail as controlled ArtifactError.
            pass

    for idx in range(250):
        mode = rng.randrange(4)
        case_path = tmp_path / f"parser-fuzz-{idx:04d}.rpk"
        if mode == 0:
            data = _random_value(rng, depth=4, allow_non_finite=False)
            case_path.write_text(
                json.dumps(data, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            serializable_case: Any = data
        elif mode == 1:
            # deterministic pseudo-random bytes to exercise UTF-8 and JSON parsing failures.
            data_bytes = bytes(rng.randrange(0, 256) for _ in range(rng.randint(8, 96)))
            case_path.write_bytes(data_bytes)
            serializable_case = {"bytes_hex": data_bytes.hex()}
        else:
            # envelope-like structure with random/missing keys.
            data = {
                "version": rng.choice(["", "0.9", "1.0", "3.0", "invalid"]),
                "metadata": _random_value(rng, depth=2, allow_non_finite=False),
                "payload": _random_value(rng, depth=2, allow_non_finite=False),
                "checksum": "sha256:" + "".join(rng.choice("0123456789abcdef") for _ in range(64)),
            }
            case_path.write_text(
                json.dumps(data, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            serializable_case = data

        try:
            envelope = read_artifact_envelope(case_path)
            assert isinstance(envelope, dict)
            assert envelope.get("version")
            assert "payload" in envelope
            assert "metadata" in envelope
            assert "checksum" in envelope
        except ArtifactError:
            pass
        except Exception as error:  # pragma: no cover - defensive path
            repro_path = _persist_repro(
                "parser",
                {
                    "index": idx,
                    "error": repr(error),
                    "case_path": str(case_path),
                    "input": serializable_case,
                },
            )
            pytest.fail(f"unexpected parser fuzz crash: {error} (repro: {repro_path})")


def test_diff_engine_fuzz_smoke_with_corpus() -> None:
    rng = random.Random(FUZZ_SEED + 2)
    left_seed = json.loads((CORPUS_ROOT / "diff" / "left_run.json").read_text(encoding="utf-8"))
    right_seed = json.loads((CORPUS_ROOT / "diff" / "right_run.json").read_text(encoding="utf-8"))
    seed_result = diff_runs(Run.from_dict(left_seed), Run.from_dict(right_seed))
    assert seed_result.total_left_steps == 1
    assert seed_result.total_right_steps == 2

    for idx in range(300):
        left_run = _random_run(rng, run_id=f"left-{idx:04d}")
        right_run = _random_run(rng, run_id=f"right-{idx:04d}")
        stop_at_first = bool(rng.getrandbits(1))
        max_changes = rng.randint(1, 16)

        try:
            result = diff_runs(
                left_run,
                right_run,
                stop_at_first_divergence=stop_at_first,
                max_changes_per_step=max_changes,
            )
        except Exception as error:  # pragma: no cover - defensive path
            repro_path = _persist_repro(
                "diff",
                {
                    "index": idx,
                    "error": repr(error),
                    "left_run": left_run.to_dict(),
                    "right_run": right_run.to_dict(),
                    "stop_at_first_divergence": stop_at_first,
                    "max_changes_per_step": max_changes,
                },
            )
            pytest.fail(f"unexpected diff fuzz crash: {error} (repro: {repro_path})")

        summary = result.summary()
        assert sum(summary.values()) == len(result.step_diffs)
        assert result.total_left_steps == len(left_run.steps)
        assert result.total_right_steps == len(right_run.steps)
