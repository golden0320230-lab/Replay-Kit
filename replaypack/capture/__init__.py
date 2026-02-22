"""Capture subsystem for ReplayKit."""

from replaypack.capture.adapters import intercept_httpx, intercept_openai_like, intercept_requests
from replaypack.capture.context import CaptureContext, capture_run, get_current_context
from replaypack.capture.demo import build_demo_run
from replaypack.capture.exceptions import BoundaryPolicyError, CaptureError, NoActiveRunError
from replaypack.capture.interceptors import (
    HttpRequest,
    HttpResponse,
    capture_http_call,
    capture_http_call_async,
    capture_model_call,
    capture_tool_call,
    tool,
)
from replaypack.capture.policy import BoundaryKind, InterceptionPolicy
from replaypack.capture.redaction import (
    DEFAULT_REDACTION_POLICY,
    RedactionPolicy,
    RedactionPolicyConfigError,
    build_redaction_policy,
    load_redaction_policy_from_file,
    redact_payload,
    redaction_policy_from_config,
)

__all__ = [
    "CaptureError",
    "NoActiveRunError",
    "BoundaryPolicyError",
    "BoundaryKind",
    "InterceptionPolicy",
    "RedactionPolicy",
    "RedactionPolicyConfigError",
    "DEFAULT_REDACTION_POLICY",
    "build_redaction_policy",
    "redaction_policy_from_config",
    "load_redaction_policy_from_file",
    "CaptureContext",
    "capture_run",
    "get_current_context",
    "build_demo_run",
    "intercept_httpx",
    "intercept_requests",
    "intercept_openai_like",
    "HttpRequest",
    "HttpResponse",
    "capture_model_call",
    "capture_tool_call",
    "capture_http_call",
    "capture_http_call_async",
    "tool",
    "redact_payload",
]
