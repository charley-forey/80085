"""Configuration is read from the environment once, validated, and shared.

Nothing in this file has a production-credential default. Local defaults exist
only for values that are safe on a developer machine; secrets must come from
the environment (spec section 17).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionTier(StrEnum):
    """How long an Experience is allowed to run for.

    Raising the global timeout would hand every anonymous stranger a
    long-running compute farm, so length is tiered instead: `quick` is the
    default and open to everyone, the longer tiers are granted per
    organization and are deliberately not self-serve.
    """

    QUICK = "quick"
    STANDARD = "standard"
    EXTENDED = "extended"


TIER_TIMEOUT_SECONDS: dict[ExecutionTier, int] = {
    ExecutionTier.QUICK: 60,
    ExecutionTier.STANDARD: 600,
    ExecutionTier.EXTENDED: 3600,
}


def tier_for_duration(seconds: int | None) -> ExecutionTier:
    """The smallest tier that covers a declared `max_duration_seconds`.

    The field already exists on the record request, so an author says how long
    they need and the platform decides which tier that lands in -- and whether
    they are allowed it. Asking for a tier by name would be asking to be
    trusted.
    """
    if seconds is None:
        return ExecutionTier.QUICK
    for tier in (ExecutionTier.QUICK, ExecutionTier.STANDARD):
        if seconds <= TIER_TIMEOUT_SECONDS[tier]:
            return tier
    return ExecutionTier.EXTENDED


class SandboxLimits(BaseSettings):
    """Policy defaults for section 15, not universal constants."""

    model_config = SettingsConfigDict(env_prefix="SANDBOX_", extra="ignore")

    cpu: float = 2.0
    memory_mb: int = 2048
    tmpfs_mb: int = 4096
    timeout_seconds: int = 60
    pids: int = 128
    max_output_bytes: int = 1_048_576
    network: bool = False

    def for_tier(self, tier: str | None) -> SandboxLimits:
        """These limits, with the wall clock the tier allows.

        Only the wall clock moves. cpu, memory, tmpfs and pids are Docker
        cgroup flags that E2B does not enforce (DECISIONS 19), so tiering them
        would be a promise one of the two runtimes silently breaks. Wall clock
        is enforced by both.

        An unknown tier is `quick`: a worker that does not understand what the
        API sent must not guess upwards.
        """
        try:
            chosen = ExecutionTier(tier or ExecutionTier.QUICK)
        except ValueError:
            chosen = ExecutionTier.QUICK
        wanted = TIER_TIMEOUT_SECONDS[chosen]
        return self.model_copy(update={"timeout_seconds": max(self.timeout_seconds, wanted)})


class EvidencePolicy(BaseSettings):
    """What it takes for a claim to become evidence (spec section 22).

    Promotion is a trust decision, not a counter. One organization can run its
    own artifact until every counter looks good -- so the number that matters
    is how many *independent* organizations have proven it, not how many runs
    there were. Configurable because a single-tenant private deployment has
    genuinely different maths from the public registry.
    """

    model_config = SettingsConfigDict(env_prefix="EVIDENCE_", extra="ignore")

    min_promotion_organizations: int = Field(default=2, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://boobs:boobs@localhost:55432/boobs"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "boobs"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"  # noqa: S105 - local MinIO default, not a secret
    s3_region: str = "us-east-1"

    artifact_registry: str = "localhost:5000"

    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = ""

    api_base_url: str = "http://localhost:8000"
    boobs_api_key: str = ""

    sandbox: SandboxLimits = Field(default_factory=SandboxLimits)
    evidence: EvidencePolicy = Field(default_factory=EvidencePolicy)

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Accept the `postgresql://` URL every hosting provider hands out.

        Railway, Heroku, Fly and friends all emit a sync-driver URL. Requiring
        the caller to rewrite it into `postgresql+asyncpg://` is a deploy-time
        footgun that costs one failed deployment to discover, so normalise it
        here instead.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value


@lru_cache
def settings() -> Settings:
    return Settings()
