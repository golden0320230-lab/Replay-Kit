from replaypack.plugins import FakeProviderAdapter


def test_fake_provider_adapter_capture_request_response_and_stream() -> None:
    adapter = FakeProviderAdapter()

    request_payload = adapter.capture_request(
        model="fake-chat",
        payload={"messages": [{"role": "user", "content": "hello"}]},
        stream=True,
    )
    assert request_payload["provider"] == "fake"
    assert request_payload["model"] == "fake-chat"
    assert request_payload["stream"] is True

    stream_payload = adapter.capture_stream(
        chunks=[
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
        ]
    )
    assert stream_payload["provider"] == "fake"
    assert stream_payload["stream"] is True
    assert stream_payload["assembled_text"] == "Hello"
    assert len(stream_payload["chunks"]) == 2

    response_payload = adapter.capture_response(
        response={"id": "resp-1", "content": "Hello"}
    )
    assert response_payload["provider"] == "fake"
    assert response_payload["stream"] is False
    assert response_payload["response"]["id"] == "resp-1"
