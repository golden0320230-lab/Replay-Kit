"""Provider adapter contracts and reference implementations."""

from replaypack.providers.base import ProviderAdapter, assemble_stream_capture
from replaypack.providers.fake import FakeProviderAdapter

__all__ = [
    "ProviderAdapter",
    "FakeProviderAdapter",
    "assemble_stream_capture",
]
