import json
from pathlib import Path

import pytest
import requests
from typer.testing import CliRunner

from replaypack.artifact import read_artifact
from replaypack.cli.app import app


def test_cli_llm_providers_lists_required_keys() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["llm", "providers"])

    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert "openai" in lines
    assert "anthropic" in lines
    assert "google" in lines


def test_cli_llm_providers_json_output() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["llm", "providers", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["artifact_path"] is None
    assert "openai" in payload["providers"]
    assert "anthropic" in payload["providers"]
    assert "google" in payload["providers"]


def test_cli_llm_fake_stream_writes_model_shaped_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "llm-fake.rpk"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "fake",
            "--model",
            "fake-chat",
            "--prompt",
            "say hello",
            "--stream",
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["provider"] == "fake"
    assert out_path.exists()

    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata.get("provider") == "fake"
    assert run.steps[1].output["output"]["assembled_text"] == "Hello"


def test_cli_llm_capture_subcommand_returns_contract_json(tmp_path: Path) -> None:
    out_path = tmp_path / "llm-capture-subcommand.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "fake",
            "--model",
            "fake-chat",
            "--prompt",
            "say hello",
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["message"]
    assert payload["artifact_path"] == str(out_path)
    assert out_path.exists()


def test_cli_llm_openai_requires_api_key() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "openai",
        ],
    )

    assert result.exit_code == 2
    assert "OPENAI_API_KEY" in result.output


def test_cli_llm_rejects_unknown_provider() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "--provider",
            "unknown",
        ],
    )

    assert result.exit_code == 2
    assert "unsupported provider" in result.output


def test_cli_llm_capture_rejects_unknown_provider_json_contract() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "unknown",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "error"
    assert payload["exit_code"] == 2
    assert payload["artifact_path"] is None
    assert "unsupported provider" in payload["message"]


def test_cli_llm_capture_redacts_secret_patterns_in_artifact(tmp_path: Path) -> None:
    out_path = tmp_path / "llm-redacted.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "fake",
            "--prompt",
            "use sk-1234567890abcdefghij please",
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    run = read_artifact(out_path)
    prompt = run.steps[0].input["input"]["payload"]["messages"][0]["content"]
    assert "[REDACTED]" in prompt
    assert "sk-1234567890abcdefghij" not in prompt


def test_cli_llm_capture_openai_uses_mock_transport_and_writes_model_steps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "id": "chatcmpl-mock-001",
                "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
            }

    def _mock_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
        stream: bool,
    ) -> _MockResponse:
        assert url.endswith("/v1/chat/completions")
        assert headers["Authorization"].startswith("Bearer ")
        assert json["model"] == "gpt-4o-mini"
        assert timeout == 30.0
        assert stream is False
        return _MockResponse()

    monkeypatch.setattr(requests, "post", _mock_post)
    out_path = tmp_path / "llm-openai-mock.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--prompt",
            "say hello",
            "--out",
            str(out_path),
            "--json",
        ],
        env={"OPENAI_API_KEY": "test-key"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["provider"] == "openai"
    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata["provider"] == "openai"
    assert run.steps[1].metadata["provider"] == "openai"


def test_cli_llm_capture_anthropic_uses_mock_transport_and_writes_provider_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "id": "msg-mock-001",
                "content": [{"type": "text", "text": "Hello"}],
            }

    def _mock_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
        stream: bool,
    ) -> _MockResponse:
        assert url.endswith("/v1/messages")
        assert headers["x-api-key"] == "test-anthropic-key"
        assert json["model"] == "claude-3-5-sonnet"
        assert timeout == 30.0
        assert stream is False
        return _MockResponse()

    monkeypatch.setattr(requests, "post", _mock_post)
    out_path = tmp_path / "llm-anthropic-mock.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "anthropic",
            "--model",
            "claude-3-5-sonnet",
            "--prompt",
            "say hello",
            "--out",
            str(out_path),
            "--json",
            "--api-key",
            "test-anthropic-key",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["provider"] == "anthropic"
    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata["provider"] == "anthropic"
    assert run.steps[1].metadata["provider"] == "anthropic"


def test_cli_llm_capture_google_uses_mock_transport_and_writes_provider_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _MockResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Hello"}],
                        }
                    }
                ]
            }

    def _mock_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
        stream: bool,
    ) -> _MockResponse:
        assert ":generateContent" in url
        assert headers["x-goog-api-key"] == "test-google-key"
        assert timeout == 30.0
        assert stream is False
        return _MockResponse()

    monkeypatch.setattr(requests, "post", _mock_post)
    out_path = tmp_path / "llm-google-mock.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            "google",
            "--model",
            "gemini-1.5-flash",
            "--prompt",
            "say hello",
            "--out",
            str(out_path),
            "--json",
            "--api-key",
            "test-google-key",
            "--base-url",
            "https://generativelanguage.googleapis.com",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "ok"
    assert payload["provider"] == "google"
    run = read_artifact(out_path)
    assert [step.type for step in run.steps] == ["model.request", "model.response"]
    assert run.steps[0].metadata["provider"] == "google"
    assert run.steps[1].metadata["provider"] == "google"


@pytest.mark.parametrize(
    ("provider", "model", "base_url", "chunks", "expected_text"),
    [
        (
            "openai",
            "gpt-4o-mini",
            "https://api.openai.com",
            [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
            ],
            "Hello",
        ),
        (
            "anthropic",
            "claude-3-5-sonnet",
            "https://api.anthropic.com",
            [
                {"delta": {"text": "Hel"}},
                {"delta": {"text": "lo"}},
            ],
            "Hello",
        ),
        (
            "google",
            "gemini-1.5-flash",
            "https://generativelanguage.googleapis.com",
            [
                {"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]},
                {"candidates": [{"content": {"parts": [{"text": "lo"}]}}]},
            ],
            "Hello",
        ),
    ],
)
def test_cli_llm_capture_streaming_records_chunks_and_assembled_text(
    provider: str,
    model: str,
    base_url: str,
    chunks: list[dict[str, object]],
    expected_text: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _MockStreamResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            lines = [f"data: {json.dumps(chunk)}".encode("utf-8") for chunk in chunks]
            lines.append(b"data: [DONE]")
            return lines

        def json(self) -> dict[str, object]:
            return {}

    def _mock_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
        stream: bool,
    ) -> _MockStreamResponse:
        assert url.startswith(base_url)
        assert json["stream"] is True
        assert timeout == 30.0
        assert stream is True
        if provider == "openai":
            assert headers["Authorization"] == "Bearer test-stream-key"
        elif provider == "anthropic":
            assert headers["x-api-key"] == "test-stream-key"
        else:
            assert headers["x-goog-api-key"] == "test-stream-key"
        return _MockStreamResponse()

    monkeypatch.setattr(requests, "post", _mock_post)
    out_path = tmp_path / f"llm-{provider}-stream.rpk"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "llm",
            "capture",
            "--provider",
            provider,
            "--model",
            model,
            "--prompt",
            "say hello",
            "--stream",
            "--api-key",
            "test-stream-key",
            "--base-url",
            base_url,
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    run = read_artifact(out_path)
    stream_payload = run.steps[1].output["output"]
    assert stream_payload["stream"] is True
    assert stream_payload["assembled_text"] == expected_text
    assert len(stream_payload["chunks"]) == 2
