"""Configuration must accept the URLs hosting providers actually emit."""

from __future__ import annotations

import pytest

from boobs_common.config import Settings


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://user:pass@host:5432/db",
        "postgres://user:pass@host:5432/db",
        "postgresql+asyncpg://user:pass@host:5432/db",
    ],
)
def test_database_url_always_uses_the_async_driver(
    given: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Railway, Heroku and Fly all hand out a sync-driver URL. Requiring the
    operator to rewrite it is a deploy-time footgun, so it is normalised."""
    monkeypatch.setenv("DATABASE_URL", given)
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_a_non_postgres_url_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///local.db")
    assert Settings().database_url == "sqlite+aiosqlite:///local.db"
