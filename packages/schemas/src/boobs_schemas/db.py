"""Engine and session factory, shared by the API and the worker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from boobs_common.config import settings


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(
        settings().database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
    )


@lru_cache
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as s:
        yield s


async def dispose() -> None:
    await engine().dispose()
    engine.cache_clear()
    session_factory.cache_clear()
