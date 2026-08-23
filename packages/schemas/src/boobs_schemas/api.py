"""Wire models for the HTTP API (spec sections 13 and 32).

These are deliberately separate from domain entities: the wire format is a
compatibility surface for agents and changes on a different clock than the
domain does.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from boobs_domain.entities import Evidence
from boobs_domain.enums import (
    Compatibility,
    ExecutionStatus,
    ExperienceStatus,
    Recommendation,
    VerificationLevel,
    Visibility,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalIn(Strict):
    statement: str = Field(min_length=3, max_length=2000)
    intent: str = Field(min_length=2, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=32)


class EnvironmentIn(Strict):
    os: str = "linux"
    architecture: str = "amd64"
    runtime: str | None = None
    runtime_version: str | None = None


class ConstraintsIn(Strict):
    network: bool = False
    max_duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    required_capabilities: list[str] = Field(default_factory=list, max_length=32)


class IOSpecIn(Strict):
    type: str
    json_schema: dict[str, Any] | None = None


class VerificationSpecIn(Strict):
    verifier: str
    config: dict[str, Any] = Field(default_factory=dict)


class LineageIn(Strict):
    derived_from: str | None = None
    forked_from: str | None = None
    improves: str | None = None
    replaces: str | None = None
    supersedes: str | None = None
    failed_variant_of: str | None = None


class ArtifactIn(Strict):
    """A reference the system is willing to execute. Must be digest-pinned."""

    type: str = "oci"
    reference: str
    size_bytes: int | None = None


class RecordExperienceRequest(Strict):
    goal: GoalIn
    artifact: ArtifactIn
    command: list[str] = Field(default_factory=list, max_length=64)
    inputs: IOSpecIn | None = None
    outputs: IOSpecIn | None = None
    environment: EnvironmentIn = EnvironmentIn()
    constraints: ConstraintsIn = ConstraintsIn()
    verification: VerificationSpecIn | None = None
    lineage: LineageIn = LineageIn()
    visibility: Visibility = Visibility.PRIVATE
    experience_id: str | None = Field(
        default=None, description="Set to add a new version to an existing Experience."
    )


class ExperienceResponse(Strict):
    experience_id: str
    version: int
    experience_version_id: str
    goal: GoalIn
    status: ExperienceStatus
    verification_level: VerificationLevel
    visibility: Visibility
    artifact_digest: str
    evidence: Evidence
    created_at: datetime


class RecallContext(Strict):
    runtime: str | None = None
    runtime_version: str | None = None
    os: str = "linux"
    architecture: str = "amd64"


class RecallRequest(Strict):
    task: str = Field(min_length=3, max_length=2000)
    context: RecallContext = RecallContext()
    constraints: ConstraintsIn = ConstraintsIn()
    limit: int = Field(default=5, ge=1, le=20)


class RecallMatch(Strict):
    experience_id: str
    version: int
    experience_version_id: str
    goal: str
    relevance: float
    compatibility: Compatibility
    confidence: float
    successful_runs: int
    recommendation: Recommendation
    requires_network: bool
    evidence: Evidence


class RecallResponse(Strict):
    matches: list[RecallMatch]
    query_id: str
    took_ms: int


class ExecuteRequest(Strict):
    version: int | None = Field(
        default=None, description="Exact version to run. Defaults to the latest."
    )
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Filename -> base64 content, staged into the sandbox working directory.",
        max_length=64,
    )
    wait_seconds: int = Field(
        default=0, ge=0, le=300, description="Block up to N seconds for a terminal status."
    )

    @field_validator("inputs")
    @classmethod
    def _decodable(cls, value: dict[str, str]) -> dict[str, str]:
        for name, blob in value.items():
            if "/" in name or "\\" in name or name.startswith("."):
                raise ValueError(f"input filename must be a plain name, got {name!r}")
            try:
                base64.b64decode(blob, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"input {name!r} is not valid base64") from exc
        return value

    def decoded_inputs(self) -> dict[str, bytes]:
        return {name: base64.b64decode(blob) for name, blob in self.inputs.items()}


class VerificationResponse(Strict):
    verification_id: str
    verifier: str
    passed: bool
    level: VerificationLevel
    detail: dict[str, Any]
    created_at: datetime


class ExecutionResponse(Strict):
    execution_id: str
    experience_id: str
    version: int
    artifact_digest: str
    status: ExecutionStatus
    exit_code: int | None = None
    duration_ms: int | None = None
    outputs: dict[str, str] = Field(default_factory=dict, description="Filename -> base64 content.")
    stdout: str | None = None
    stderr: str | None = None
    error: str | None = None
    verification: VerificationResponse | None = None
    created_at: datetime


class VerifyRequest(Strict):
    verifier: str | None = Field(
        default=None, description="Defaults to the version's declared verifier."
    )
    config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _config_needs_verifier(self) -> Self:
        if self.config is not None and self.verifier is None:
            raise ValueError("config may only be supplied together with an explicit verifier")
        return self


class EventResponse(Strict):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
