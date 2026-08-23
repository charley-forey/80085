"""Closed vocabularies shared by every layer."""

from __future__ import annotations

from enum import StrEnum


class Visibility(StrEnum):
    PRIVATE = "private"
    ORGANIZATION = "organization"
    PUBLIC = "public"


class ExperienceStatus(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"


class VerificationLevel(StrEnum):
    """The distinction the product rests on (spec section 18)."""

    UNVERIFIED = "unverified"
    CLAIMED = "claimed"
    PROVEN = "proven"


class ArtifactType(StrEnum):
    OCI = "oci"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


class Recommendation(StrEnum):
    USE = "use"
    CONSIDER = "consider"
    AVOID = "avoid"


class Compatibility(StrEnum):
    HIGH = "high"
    PARTIAL = "partial"
    NONE = "none"
