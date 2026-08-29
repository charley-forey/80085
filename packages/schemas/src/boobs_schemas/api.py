"""Wire models for the HTTP API (spec sections 13 and 32).

These are deliberately separate from domain entities: the wire format is a
compatibility surface for agents and changes on a different clock than the
domain does.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from boobs_common.config import ExecutionTier
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


class BootstrapRequest(Strict):
    """Mints an organization, an agent and its first API key.

    A single model rather than several Body(embed=True) parameters: sharing one
    Body marker across parameters silently mis-parses the request, which is a
    very quiet way to make every credential check fail.
    """

    organization: str = Field(min_length=1, max_length=200)
    agent: str = Field(min_length=1, max_length=200)
    token: str = Field(min_length=1)
    scopes: list[str] | None = Field(
        default=None,
        description='Defaults to the ordinary agent scopes. Pass ["worker:execute"] for a worker.',
    )


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


class ProvisionAgentRequest(Strict):
    """A key for one more person or system inside an existing organization.

    `name` is how they appear in every question and answer they produce, so it
    wants to be somebody a colleague can go and ask -- not "agent-4".
    """

    name: str = Field(min_length=1, max_length=200)


class VerifyAnswerRequest(Strict):
    """A second human saying an answer is true generally, not just for them."""

    verified_by: str = Field(min_length=1, max_length=200)


class RecordQuestionRequest(Strict):
    """A halt: what an agent could not determine and refused to guess at.

    `need` is the agent's own words. It is free text from a caller and is
    treated as such wherever it is rendered back.
    """

    need: str = Field(min_length=8, max_length=2000)
    context: dict[str, Any] | None = None


class AnswerQuestionRequest(Strict):
    """What somebody said, once, so nothing has to ask again.

    `answered_by` is required and free text: a name a colleague can walk to.
    An answer without an owner is a rumour, and since decision 74 an agent told
    to defer will believe a rumour as readily as a fact.
    """

    body: str = Field(min_length=1, max_length=8000)
    answered_by: str = Field(min_length=1, max_length=200)


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
    # Public by default, because a shared brain whose contributions default to
    # invisible is not shared. This is only safe because recording is not the
    # same as being recommended: ranking weights a Wilson lower bound over
    # verified runs, so an unproven Experience is visible but never returned as
    # "use". Pass visibility explicitly to keep something to yourself.
    visibility: Visibility = Visibility.PUBLIC
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
    # A sparse map rather than `LineageIn`, so five unset relations do not cost
    # five nulls on every experience read. It is what was recorded, verbatim
    # and unresolved: nothing validates a lineage id at write time, so an entry
    # here is a claim about provenance, not a promise that the id exists or
    # that this caller may see it. `GET .../lineage` is what resolves them.
    lineage: dict[str, str] = Field(
        default_factory=dict, description="Relation -> experience id, as recorded."
    )
    created_at: datetime


class LineageNode(Strict):
    """One lineage edge, resolved as far as this caller is allowed to see.

    An edge whose target is another organization's private Experience and an
    edge whose target was never recorded produce the *same* node: the id, and
    `resolved: false`. That is deliberate -- distinguishing them would turn
    traversal into an oracle for whether an id exists, which is exactly what
    the visibility rules exist to prevent.
    """

    from_experience_id: str
    relation: str
    experience_id: str
    depth: int
    resolved: bool
    goal: str | None = None
    status: ExperienceStatus | None = None
    verification_level: VerificationLevel | None = None
    latest_version: int | None = None


class LineageResponse(Strict):
    experience_id: str
    depth: int
    nodes: list[LineageNode] = Field(
        description="Breadth-first, nearest edges first. Each Experience appears once, "
        "by its shortest path, which is what makes a cycle terminate."
    )
    truncated: bool = Field(
        default=False, description="True when the node budget ran out before the graph did."
    )


class GrantExecutionTiersRequest(Strict):
    """Which execution tiers one organization may ask for.

    A set, not a delta: what you send is what the row ends up saying, so
    `{"tiers": []}` is how a grant is taken back. `reason` is required and
    stored, because the row is the whole audit trail -- an hour of compute
    approved with no stated cause is indistinguishable from a leaked admin key.
    """

    tiers: list[ExecutionTier] = Field(max_length=len(ExecutionTier))
    reason: str = Field(min_length=8, max_length=500)


class ExecutionTiersResponse(Strict):
    organization_id: str
    granted: list[str] = Field(description="What this grant row now says.")
    effective: list[str] = Field(
        description="What the organization can actually ask for, across every policy row. "
        "Differs from `granted` only when an operator inserted a row by hand."
    )
    reason: str
    granted_by: str
    granted_at: datetime


class QuarantineRequest(Strict):
    """Withdraw one Experience from recall, or put it back.

    One field rather than two endpoints, for the reason a tier grant is a set
    rather than a delta: what you send is what the row ends up saying, so
    repeating a request cannot accumulate anything and there is a way back that
    is not an operator typing UPDATE. `reason` is required in both directions
    -- releasing something that was withdrawn for cause is exactly as much a
    judgement as withdrawing it, and the row is the whole audit trail.
    """

    quarantined: bool
    reason: str = Field(min_length=8, max_length=500)


class QuarantineResponse(Strict):
    experience_id: str
    status: str = Field(description="What the Experience's status now is.")
    quarantine: dict[str, Any] | None = Field(
        default=None,
        description="Why it is quarantined, who decided and when. Null once it is not.",
    )


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
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            "Retry token. Repeating a request with the same key returns the execution the "
            "first one created rather than running the sandbox a second time. Scoped to "
            "your organization; pick something unique to the attempt, such as a uuid4."
        ),
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
    """Deliberately empty, and `Strict` so that stays true.

    Re-verification uses the verifier the *version* declared, never one the
    caller names. The owner of an execution could otherwise re-verify their own
    run under a weaker verifier -- swap a sha256 match for `exit_code` -- and
    manufacture a passing row that ranking would then count as evidence.
    Changing how something is verified is a change to the Experience, so it
    needs a new version, not a request parameter.
    """


class RecallMissOut(Strict):
    """One gap: something agents asked for and the corpus did not have.

    Carries no free text. `intent` and `terms` are both drawn from closed
    tables in `boobs_retrieval.intent`, so nothing a caller typed reaches a
    reader of this model -- see decision 49. `cleared` is not returned because
    a miss is by definition a recall where it was zero.
    """

    intent: str
    terms: str = Field(description="Recognized action and format labels, or empty.")
    environment: dict[str, Any] = Field(description="The compatibility filters that applied.")
    constraints: dict[str, Any]
    candidates: int = Field(description="Candidates that survived retrieval.")
    best_score: float = Field(
        description="The closest any candidate ever came. Low means the corpus "
        "has a hole; just under threshold means ranking is too strict."
    )
    occurrences: int
    organization_id: str | None = Field(
        default=None, description="Null for the anonymous majority; recall needs no key."
    )
    first_seen_at: datetime
    last_seen_at: datetime


class RecallMissesResponse(Strict):
    misses: list[RecallMissOut]
    next_offset: int | None = Field(
        default=None, description="Pass as `offset` for the next page. Null on the last one."
    )


class EventResponse(Strict):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
