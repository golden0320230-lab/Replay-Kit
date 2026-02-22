import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import compute_artifact_checksum, read_artifact
from replaypack.cli.app import app
from replaypack.core.hashing import compute_step_hash
from replaypack.replay import ReplayConfig, replay_stub_run


def _write_legacy_v0_9(path: Path, *, version: str = "0.9") -> None:
    request_payload = {"query": "weather sf"}
    response_payload = {"status": "ok"}
    metadata = {"tool": "search"}
    step_hash = compute_step_hash("tool.request", request_payload, response_payload, metadata)

    artifact = {
        "version": version,
        "metadata": {
            "run_id": "run-cli-legacy-001",
            "created_at": "2026-02-22T20:00:00Z",
        },
        "payload": {
            "run": {
                "id": "run-cli-legacy-001",
                "timestamp": "2026-02-22T20:00:00Z",
                "env_fingerprint": {"os": "macOS"},
                "runtime": {"python": "3.11.9", "replaykit": "0.0.9"},
                "steps": [
                    {
                        "id": "step-000001",
                        "type": "tool.request",
                        "request": request_payload,
                        "response": response_payload,
                        "metadata": metadata,
                        "step_hash": step_hash,
                    }
                ],
            }
        },
    }
    artifact["checksum"] = compute_artifact_checksum(
        {
            "version": artifact["version"],
            "metadata": artifact["metadata"],
            "payload": artifact["payload"],
        }
    )
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_cli_migrate_legacy_success_and_replay_compatible(tmp_path: Path) -> None:
    source = tmp_path / "legacy-0.9.rpk"
    out = tmp_path / "migrated.rpk"
    _write_legacy_v0_9(source)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["migrate", str(source), "--out", str(out), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "pass"
    assert payload["source_version"] == "0.9"
    assert payload["target_version"] == "1.0"
    assert payload["preserved_step_hashes"] == 1

    migrated_run = read_artifact(out)
    replayed_run = replay_stub_run(
        migrated_run,
        config=ReplayConfig(seed=9, fixed_clock="2026-02-22T20:30:00Z"),
    )
    assert len(replayed_run.steps) == len(migrated_run.steps)
    assert replayed_run.environment_fingerprint["replay_offline"] is True


def test_cli_migrate_unsupported_version_non_zero(tmp_path: Path) -> None:
    source = tmp_path / "unsupported.rpk"
    out = tmp_path / "migrated.rpk"
    _write_legacy_v0_9(source, version="3.0")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["migrate", str(source), "--out", str(out), "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert "unsupported source artifact version" in payload["message"]
