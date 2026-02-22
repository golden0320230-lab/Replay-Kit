from replaypack.providers import FakeProviderAdapter, assemble_stream_capture


def test_provider_adapter_contract_stream_assembly_is_deterministic() -> None:
    adapter = FakeProviderAdapter()
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
    ]

    first = assemble_stream_capture(adapter, chunks=chunks)
    second = assemble_stream_capture(adapter, chunks=chunks)

    assert first == second
    assert first["provider"] == "fake"
    assert first["assembled_text"] == "Hello"
    assert [chunk["delta_text"] for chunk in first["chunks"]] == ["Hel", "lo"]


def test_provider_adapter_contract_request_and_response_shape() -> None:
    adapter = FakeProviderAdapter()

    request_payload = adapter.capture_request(
        model="fake-chat",
        payload={"messages": [{"role": "user", "content": "hello"}]},
        stream=True,
    )
    response_payload = adapter.capture_response(
        response={"id": "resp-1", "content": "Hello"},
    )

    assert request_payload["provider"] == "fake"
    assert request_payload["model"] == "fake-chat"
    assert request_payload["stream"] is True

    assert response_payload["provider"] == "fake"
    assert response_payload["stream"] is False
    assert response_payload["response"]["id"] == "resp-1"
