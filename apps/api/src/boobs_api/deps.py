"""Request-scoped dependencies: database session and authenticated principal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common.clock import now
from boobs_common.errors import Unauthorized
from boobs_domain.protocols import Principal
from boobs_schemas.db import session_factory
from boobs_schemas.tables import ApiKey
from boobs_security.keys import hash_key, looks_like_key


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_principal(
    db: DbSession, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    """Resolve an API key to a principal.

    Lookup is by hash: the plaintext key is never stored, so a database dump
    does not yield working credentials.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not looks_like_key(token):
        raise Unauthorized("malformed api key")

    record = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_key(token)))
    ).scalar_one_or_none()
    if record is None:
        raise Unauthorized("unknown api key")
    if record.revoked_at is not None:
        raise Unauthorized("api key revoked")

    record.last_used_at = now()  # audit trail; committed with the request
    return Principal(
        organization_id=record.organization_id,
        agent_id=record.agent_id,
        scopes=frozenset(record.scopes or ()),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
