"""Replaceable contracts (spec section 10).

Infrastructure implements these. Domain logic depends only on them, so the
Docker runtime can become Firecracker, gVisor or WASI, and Postgres can become
something else, without the product domain changing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from boobs_domain.entities import (
    Artifact,
    Constraints,
    Environment,
    Evidence,
    Execution,
    ExecutionEvent,
    Experience,
    ExperienceVersion,
    RecallCandidate,
    VerificationSpec,
)
from boobs_domain.enums import ExecutionStatus, VerificationLevel


class Principal(BaseModel):
    """Who is asking. Every repository call is scoped by this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str
    agent_id: str
    scopes: frozenset[str] = frozenset()


class RecallQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=3, max_length=2000)
    environment: Environment = Environment()
    constraints: Constraints = Constraints()
    limit: int = Field(default=5, ge=1, le=20)


class SandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    image: str
    command: Sequence[str] = ()
    input_files: dict[str, bytes] = Field(default_factory=dict)
    output_paths: Sequence[str] = ()
    env: dict[str, str] = Field(default_factory=dict)
    cpu: float
    memory_mb: int
    tmpfs_mb: int
    timeout_seconds: int
    pids: int
    max_output_bytes: int
    network: bool = False


class SandboxResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExecutionStatus
    exit_code: int | None
    duration_ms: int
    stdout: bytes = b""
    stderr: bytes = b""
    output_files: dict[str, bytes] = Field(default_factory=dict)
    truncated: bool = False
    error: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    level: VerificationLevel
    detail: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ExperienceRepository(Protocol):
    async def create(
        self, principal: Principal, experience: Experience, version: ExperienceVersion
    ) -> tuple[Experience, ExperienceVersion]: ...

    async def get(self, principal: Principal, experience_id: str) -> Experience: ...

    async def get_version(
        self, principal: Principal, experience_id: str, version: int | None = None
    ) -> ExperienceVersion: ...

    async def search(self, principal: Principal, query: RecallQuery) -> list[RecallCandidate]: ...

    async def evidence(self, experience_id: str, version: int) -> Evidence: ...


@runtime_checkable
class ArtifactRepository(Protocol):
    async def register(self, principal: Principal, reference: str) -> Artifact: ...

    async def resolve(self, artifact_id: str) -> Artifact: ...


@runtime_checkable
class ExecutionRuntime(Protocol):
    async def execute(self, request: SandboxRequest) -> SandboxResult: ...


@runtime_checkable
class Verifier(Protocol):
    async def verify(
        self, result: SandboxResult, specification: VerificationSpec
    ) -> VerificationResult: ...


@runtime_checkable
class EventStore(Protocol):
    async def append(
        self, execution_id: str, event_type: str, payload: dict[str, Any]
    ) -> ExecutionEvent: ...

    def stream(self, execution_id: str) -> AsyncIterator[ExecutionEvent]: ...


@runtime_checkable
class PolicyEngine(Protocol):
    async def authorize(
        self, principal: Principal, action: str, resource: object | None = None
    ) -> None:
        """Raise Forbidden if the action is not permitted. Return None if it is."""
        ...


@runtime_checkable
class ExecutionRepository(Protocol):
    async def create(self, execution: Execution) -> Execution: ...

    async def get(self, principal: Principal, execution_id: str) -> Execution: ...

    async def complete(self, execution_id: str, result: SandboxResult) -> Execution: ...
