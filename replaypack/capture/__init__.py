"""Capture subsystem for ReplayKit."""

from replaypack.capture.context import CaptureContext, capture_run, get_current_context
from replaypack.capture.demo import build_demo_run
from replaypack.capture.exceptions import BoundaryPolicyError, CaptureError, NoActiveRunError
from replaypack.capture.interceptors import (
    HttpRequest,
    HttpResponse,
    capture_http_call,
    capture_model_call,
    capture_tool_call,
    tool,
)
from replaypack.capture.policy import BoundaryKind, InterceptionPolicy
from replaypack.capture.redaction import DEFAULT_REDACTION_POLICY, RedactionPolicy, redact_payload

__all__ = [
    "CaptureError",
    "NoActiveRunError",
    "BoundaryPolicyError",
    "BoundaryKind",
    "InterceptionPolicy",
    "RedactionPolicy",
    "DEFAULT_REDACTION_POLICY",
    "CaptureContext",
    "capture_run",
    "get_current_context",
    "build_demo_run",
    "HttpRequest",
    "HttpResponse",
    "capture_model_call",
    "capture_tool_call",
    "capture_http_call",
    "tool",
    "redact_payload",
]
