"""Core data models for ReplayKit runs and steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from replaypack.core.hashing import compute_step_hash
from replaypack.core.types import STEP_TYPES


@dataclass(slots=True)
class Step:
    """A single deterministic diff unit in a run."""

    id: str
    type: str
    input: Any
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None
    hash: str | None = None

    def __post_init__(self) -> None:
        if self.type not in STEP_TYPES:
            raise ValueError(f"Unsupported step type: {self.type}")

    def with_hash(self) -> "Step":
        """Return a copy with deterministic hash computed."""
        return Step(
            id=self.id,
            type=self.type,
            input=self.input,
            output=self.output,
            metadata=dict(self.metadata),
            timestamp=self.timestamp,
            hash=compute_step_hash(self.type, self.input, self.output, self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        computed_hash = self.hash or compute_step_hash(
            self.type,
            self.input,
            self.output,
            self.metadata,
        )
        return {
            "id": self.id,
            "type": self.type,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "hash": computed_hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Step":
        return cls(
            id=raw["id"],
            type=raw["type"],
            input=raw.get("input"),
            output=raw.get("output"),
            metadata=dict(raw.get("metadata", {})),
            timestamp=raw.get("timestamp"),
            hash=raw.get("hash"),
        )


@dataclass(slots=True)
class Run:
    """An ordered run of AI workflow steps."""

    id: str
    timestamp: str
    environment_fingerprint: dict[str, Any]
    runtime_versions: dict[str, Any]
    source: str | None = None
    provider: str | None = None
    agent: str | None = None
    steps: list[Step] = field(default_factory=list)

    def with_hashed_steps(self) -> "Run":
        return Run(
            id=self.id,
            timestamp=self.timestamp,
            source=self.source,
            provider=self.provider,
            agent=self.agent,
            environment_fingerprint=dict(self.environment_fingerprint),
            runtime_versions=dict(self.runtime_versions),
            steps=[step.with_hash() for step in self.steps],
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "timestamp": self.timestamp,
            "environment_fingerprint": self.environment_fingerprint,
            "runtime_versions": self.runtime_versions,
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.source is not None:
            payload["source"] = self.source
        if self.provider is not None:
            payload["provider"] = self.provider
        if self.agent is not None:
            payload["agent"] = self.agent
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Run":
        return cls(
            id=raw["id"],
            timestamp=raw["timestamp"],
            source=raw.get("source"),
            provider=raw.get("provider"),
            agent=raw.get("agent"),
            environment_fingerprint=dict(raw.get("environment_fingerprint", {})),
            runtime_versions=dict(raw.get("runtime_versions", {})),
            steps=[Step.from_dict(step) for step in raw.get("steps", [])],
        )
