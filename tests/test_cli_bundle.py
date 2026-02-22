import json
from pathlib import Path

from typer.testing import CliRunner

from replaypack.artifact import read_artifact, write_artifact
from replaypack.cli.app import app
from replaypack.core.models import Run, Step


def _source_artifact(tmp_path: Path) -> Path:
    source = tmp_path / "source.rpk"
    run = Run(
        id="run-cli-bundle-001",
        timestamp="2026-02-21T21:00:00Z",
        environment_fingerprint={"os": "macOS"},
        runtime_versions={"python": "3.12.1", "replaykit": "0.1.0"},
        steps=[
            Step(
                id="step-001",
                type="tool.request",
                input={"token": "sk-cli-secret-1234567890", "email": "cli@example.com"},
                output={"status": "sent"},
                metadata={"provider": "cli"},
            )
        ],
    )
    write_artifact(run, source)
    return source


def test_cli_bundle_default_profile(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "incident.bundle"

    runner = CliRunner()
    result = runner.invoke(app, ["bundle", str(source), "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()

    run = read_artifact(out)
    assert run.steps[0].input["token"] == "[REDACTED]"


def test_cli_bundle_json_output(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "incident.bundle"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "bundle",
            str(source),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["mode"] == "bundle"
    assert payload["redaction_profile"] == "default"


def test_cli_bundle_none_profile(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "raw.bundle"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "bundle",
            str(source),
            "--out",
            str(out),
            "--redact",
            "none",
        ],
    )

    assert result.exit_code == 0
    run = read_artifact(out)
    assert run.steps[0].input["token"].startswith("sk-cli-secret")


def test_cli_bundle_invalid_profile_returns_non_zero(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "bad.bundle"

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "bundle",
            str(source),
            "--out",
            str(out),
            "--redact",
            "invalid",
        ],
    )

    assert result.exit_code == 1
    combined_output = result.stdout + result.stderr
    assert "bundle failed" in combined_output


def test_cli_bundle_redaction_config_applies_custom_policy(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "custom.bundle"
    config = tmp_path / "redaction.json"
    config.write_text(
        json.dumps({"extra_sensitive_field_names": ["provider"]}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "bundle",
            str(source),
            "--out",
            str(out),
            "--redaction-config",
            str(config),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["redaction_profile"] == "custom"

    run = read_artifact(out)
    assert run.steps[0].metadata["provider"] == "[REDACTED]"


def test_cli_bundle_redaction_config_rejects_non_default_profile(tmp_path: Path) -> None:
    source = _source_artifact(tmp_path)
    out = tmp_path / "bad.bundle"
    config = tmp_path / "redaction.json"
    config.write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "bundle",
            str(source),
            "--out",
            str(out),
            "--redact",
            "none",
            "--redaction-config",
            str(config),
        ],
    )

    assert result.exit_code == 2
    assert "can only be used with --redact default" in (result.stdout + result.stderr)
