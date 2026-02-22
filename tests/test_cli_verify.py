import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import compute_artifact_checksum, write_artifact
from replaypack.cli.app import app
from replaypack.core.models import Run, Step


def _artifact_run() -> Run:
    return Run(
        id="run-cli-verify-001",
        timestamp="2026-02-22T16:30:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.0", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-001",
                type="tool.request",
                input={"token": "sk-cli-verify-token"},
                output={"status": "sent"},
                metadata={"provider": "cli"},
            ),
            Step(
                id="step-002",
                type="tool.response",
                input={"ok": True},
                output={"content": "ok"},
                metadata={"provider": "cli"},
            ),
        ],
    )


def test_cli_verify_passes_for_valid_signed_artifact(tmp_path: Path) -> None:
    path = tmp_path / "signed.rpk"
    write_artifact(_artifact_run(), path, sign=True, signing_key="verify-key")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "verify",
            str(path),
            "--signing-key",
            "verify-key",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["valid"] is True
    assert payload["status"] == "verified"


def test_cli_verify_fails_for_signature_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "signed.rpk"
    write_artifact(_artifact_run(), path, sign=True, signing_key="verify-key")

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

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "verify",
            str(path),
            "--signing-key",
            "verify-key",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip())
    assert payload["valid"] is False
    assert payload["status"] == "invalid_signature"


def test_cli_verify_missing_signature_behavior(tmp_path: Path) -> None:
    path = tmp_path / "unsigned.rpk"
    write_artifact(_artifact_run(), path)

    runner = CliRunner()

    strict_result = runner.invoke(app, ["verify", str(path), "--json"])
    assert strict_result.exit_code == 1
    strict_payload = json.loads(strict_result.stdout.strip())
    assert strict_payload["status"] == "missing_signature"

    allow_result = runner.invoke(
        app,
        ["verify", str(path), "--allow-unsigned", "--json"],
    )
    assert allow_result.exit_code == 0
    allow_payload = json.loads(allow_result.stdout.strip())
    assert allow_payload["status"] == "unsigned_allowed"


def test_cli_record_sign_writes_signature(tmp_path: Path) -> None:
    out = tmp_path / "record-signed.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["record", "--out", str(out), "--sign"],
        env={"REPLAYKIT_SIGNING_KEY": "record-key"},
    )

    assert result.exit_code == 0
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["signature"]["algorithm"] == "hmac-sha256"
    assert raw["signature"]["key_id"] == "default"


def test_cli_bundle_sign_writes_signature(tmp_path: Path) -> None:
    source = tmp_path / "source.rpk"
    out = tmp_path / "bundle-signed.bundle"
    write_artifact(_artifact_run(), source)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["bundle", str(source), "--out", str(out), "--sign"],
        env={"REPLAYKIT_SIGNING_KEY": "bundle-key"},
    )

    assert result.exit_code == 0
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["signature"]["algorithm"] == "hmac-sha256"
    assert raw["signature"]["key_id"] == "default"
