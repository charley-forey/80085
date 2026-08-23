"""Domain entities.

Pure data plus the invariants that must hold everywhere. No database, no HTTP,
no driver imports -- infrastructure implements the protocols in protocols.py,
never the other way round.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from boobs_domain.enums import (
    ArtifactType,
    Compatibility,
    ExecutionStatus,
    ExperienceStatus,
    Recommendation,
    VerificationLevel,
    Visibility,
)

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# An OCI reference we are willing to execute: repository@sha256:<64 hex>.
# Tags are rejected at the boundary -- never execute a floating reference
# (spec section 5).
OCI_PINNED_RE = re.compile(r"^[a-zA-Z0-9._:\-/]+@sha256:[0-9a-f]{64}$")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Goal(Frozen):
    statement: str = Field(min_length=3, max_length=2000)
    intent: str = Field(min_length=2, max_length=200)
    tags: tuple[str, ...] = ()


class Environment(Frozen):
    os: str = "linux"
    architecture: str = "amd64"
    runtime: str | None = None
    runtime_version: str | None = None


class Constraints(Frozen):
    network: bool = False
    max_duration_seconds: int | None = None
    required_capabilities: tuple[str, ...] = ()


class IOSpec(Frozen):
    """What goes in and what comes out, by media type."""

    type: str
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Lineage(Frozen):
    """Foundation of the future Experience Graph (spec section 5)."""

    derived_from: str | None = None
    forked_from: str | None = None
    improves: str | None = None
    replaces: str | None = None
    supersedes: str | None = None
    failed_variant_of: str | None = None


class Artifact(Frozen):
    id: str
    type: ArtifactType = ArtifactType.OCI
    reference: str
    digest: str
    size_bytes: int | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _pinned(self) -> Self:
        if not DIGEST_RE.match(self.digest):
            raise ValueError(f"artifact digest must be sha256:<64 hex>, got {self.digest!r}")
        if self.type is ArtifactType.OCI and not OCI_PINNED_RE.match(self.reference):
            raise ValueError(
                "OCI artifacts must be pinned as repository@sha256:<digest>; "
                f"got {self.reference!r}"
            )
        if self.type is ArtifactType.OCI and not self.reference.endswith(self.digest):
            raise ValueError("artifact reference digest does not match artifact digest")
        return self


class VerificationSpec(Frozen):
    """How an execution of this version is proven to have worked."""

    verifier: str
    config: dict[str, Any] = Field(default_factory=dict)


class ExperienceVersion(Frozen):
    id: str
    experience_id: str
    version: int = Field(ge=1)
    artifact_id: str
    command: tuple[str, ...] = ()
    inputs: IOSpec | None = None
    outputs: IOSpec | None = None
    environment: Environment = Environment()
    constraints: Constraints = Constraints()
    verification: VerificationSpec | None = None
    lineage: Lineage = Lineage()
    created_by: str
    created_at: datetime


class Evidence(BaseModel):
    """Answers the only question an agent has: will this probably work for me?
    (spec section 19). Every field is derived from immutable execution rows."""

    model_config = ConfigDict(extra="forbid")

    successful_runs: int = 0
    failed_runs: int = 0
    success_rate: float = 0.0
    confidence: float = 0.0
    last_verified_at: datetime | None = None
    median_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    distinct_organizations: int = 0
    failure_modes: dict[str, int] = Field(default_factory=dict)


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    organization_id: str
    goal: Goal
    status: ExperienceStatus = ExperienceStatus.DRAFT
    verification_level: VerificationLevel = VerificationLevel.UNVERIFIED
    visibility: Visibility = Visibility.PRIVATE
    latest_version: int = 0
    created_by: str
    created_at: datetime
    updated_at: datetime


class Execution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    organization_id: str
    agent_id: str
    experience_id: str
    experience_version_id: str
    artifact_digest: str
    status: ExecutionStatus = ExecutionStatus.QUEUED
    exit_code: int | None = None
    duration_ms: int | None = None
    output_key: str | None = None
    logs_key: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ExecutionEvent(Frozen):
    id: str
    execution_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Verification(Frozen):
    id: str
    execution_id: str
    verifier: str
    passed: bool
    level: VerificationLevel
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Organization(Frozen):
    id: str
    name: str
    created_at: datetime


class Agent(Frozen):
    id: str
    organization_id: str
    name: str
    created_at: datetime


class RecallCandidate(BaseModel):
    """One row of a recall response (spec section 13 output shape)."""

    model_config = ConfigDict(extra="forbid")

    experience_id: str
    version: int
    experience_version_id: str
    goal: str
    relevance: float
    compatibility: Compatibility
    confidence: float
    successful_runs: int
    recommendation: Recommendation
    evidence: Evidence
    requires_network: bool
