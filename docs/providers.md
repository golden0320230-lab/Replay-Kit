# Provider Adapter Contract

ReplayKit uses provider adapters to normalize model request/stream/response payloads
before capture.

## Contract

Defined in `replaypack/plugins/provider_api.py`:

- `ProviderAdapter.capture_request(model, payload, stream) -> dict`
- `ProviderAdapter.capture_stream(chunks) -> dict`
- `ProviderAdapter.capture_response(response) -> dict`

The interface is intentionally small so adapters can be added for OpenAI,
Anthropic, local runtimes, or internal gateways without changing core capture code.

## Reference Adapter

`replaypack/plugins/fake_provider_adapter.py` includes `FakeProviderAdapter`, used
for the fake provider in live-demo workflows.

Expected behavior:

- Request payloads include provider/model/stream metadata.
- Stream payloads preserve chunks and include assembled text.
- Non-stream responses are wrapped in a normalized envelope.
