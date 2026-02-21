"""Interception policy controls for capture boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from replaypack.capture.exceptions import BoundaryPolicyError

BoundaryKind = Literal["model", "tool", "http"]


@dataclass(slots=True)
class InterceptionPolicy:
    """Policy for allowing or denying capture boundary execution."""

    allow_model: bool = True
    allow_tool: bool = True
    allow_http: bool = True
    allowed_hosts: frozenset[str] | None = None
    blocked_hosts: frozenset[str] = field(default_factory=frozenset)
    capture_http_bodies: bool = False

    def assert_allowed(self, boundary: BoundaryKind, target: str) -> None:
        if boundary == "model" and not self.allow_model:
            raise BoundaryPolicyError(
                "Model boundary denied by policy. Set allow_model=True to capture model calls."
            )

        if boundary == "tool" and not self.allow_tool:
            raise BoundaryPolicyError(
                "Tool boundary denied by policy. Set allow_tool=True to capture tool calls."
            )

        if boundary == "http":
            if not self.allow_http:
                raise BoundaryPolicyError(
                    "HTTP boundary denied by policy. Set allow_http=True to capture HTTP calls."
                )

            host = _extract_host(target)
            if host in self.blocked_hosts:
                raise BoundaryPolicyError(
                    "HTTP boundary denied by policy for blocked host "
                    f"'{host}'. Remove it from blocked_hosts to allow this call."
                )

            if self.allowed_hosts is not None and host not in self.allowed_hosts:
                raise BoundaryPolicyError(
                    "HTTP boundary denied by policy for host "
                    f"'{host}'. Add host to allowed_hosts to allow this call."
                )


def _extract_host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower()
