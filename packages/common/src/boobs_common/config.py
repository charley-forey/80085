"""Configuration is read from the environment once, validated, and shared.

Nothing in this file has a production-credential default. Local defaults exist
only for values that are safe on a developer machine; secrets must come from
the environment (spec section 17).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
