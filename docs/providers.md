# Provider Adapter Contract

ReplayKit uses provider adapters to normalize model request/stream/response payloads
before capture.

## Contract

Defined in `replaypack/providers/base.py`:

- `ProviderAdapter.capture_request(model, payload, stream) -> dict`
- `ProviderAdapter.capture_stream_chunk(chunk) -> dict`
- `ProviderAdapter.capture_response(response) -> dict`

The interface is intentionally small so adapters can be added for OpenAI,
Anthropic, local runtimes, or internal gateways without changing core capture code.

## Reference Adapter

`replaypack/providers/fake.py` includes `FakeProviderAdapter`, used for
deterministic local provider-shaped capture flows.

Expected behavior:

- Request payloads include provider/model/stream metadata.
- Stream chunk payloads preserve chunk structure and expose `delta_text`.
- Stream assembly combines normalized chunks into deterministic `assembled_text`.
- Non-stream responses are wrapped in a normalized envelope.
