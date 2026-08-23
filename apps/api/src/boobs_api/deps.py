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
from boobs_security.keys import Scope, hash_key, looks_like_key


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


# Reading is free. This principal belongs to no organization, and because
# visibility_clause() scopes every search to PUBLIC or the caller's own org,
# it can therefore see public Experiences and nothing else. The restriction is
# the existing predicate rather than a second code path that could disagree
# with it.
ANONYMOUS = Principal(
    organization_id="org_anonymous",
    agent_id="agt_anonymous",
    scopes=frozenset({Scope.EXPERIENCES_READ}),
)


async def get_principal_or_anonymous(
    db: DbSession, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    """Resolve a key if one was sent, otherwise read as nobody.

    Only an *absent* credential is anonymous. A malformed, unknown or revoked
    key still fails: silently downgrading a bad key to anonymous would turn a
    caller's expired credential into a permission change they never asked for,
    and would hide key rotation bugs from whoever has to debug them.
    """
    if authorization is None or not authorization.strip():
        return ANONYMOUS
    return await get_principal(db, authorization)


MaybePrincipal = Annotated[Principal, Depends(get_principal_or_anonymous)]
