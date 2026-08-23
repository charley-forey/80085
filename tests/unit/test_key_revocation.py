"""Who may revoke whose key.

`revoked_at` was checked at authentication and set by nothing, so
docs/security.md's "revocable" meant an UPDATE run by hand against
production. The interesting half of adding the route is not that revocation
works -- it is that revocation is a denial-of-service primitive pointed at
whoever's key id you can name, and keys mint anonymously with no account
behind them.

So: your organization's keys, or `admin`. Nothing else.

The same rules are asserted end to end, over HTTP and a real database, in
tests/integration/test_key_revocation.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from boobs_api import routes
from boobs_common.clock import now
from boobs_common.errors import Forbidden
from boobs_domain.protocols import Principal
from boobs_schemas.tables import ApiKey
from boobs_security.keys import Scope

MINE = "org_mine"
THEIRS = "org_theirs"


class Session:
    def __init__(self, row: Any) -> None:
        self._row = row
        self.committed = False

    async def execute(self, *_: Any, **__: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: self._row)

    async def commit(self) -> None:
        self.committed = True


def a_key(organization_id: str) -> ApiKey:
    return ApiKey(
        id="key_target",
        organization_id=organization_id,
        agent_id="agt_target",
        name="target",
        key_hash="a" * 64,
        scopes=[Scope.EXPERIENCES_READ],
        created_at=now(),
    )


def a_principal(organization_id: str, *scopes: str) -> Principal:
    return Principal(
        organization_id=organization_id, agent_id="agt_caller", scopes=frozenset(scopes)
    )


async def test_an_organization_can_revoke_its_own_key() -> None:
    """No scope is demanded beyond holding a key of the organization.

    There is no account to log into and a self-serve organization holds
    exactly one key, so the organization is the only owner there is -- and it
    is precisely the set a contributor has to be able to burn.
    """
    key = a_key(MINE)
    await routes.revoke_key(
        key_id=key.id,
        db=Session(key),  # type: ignore[arg-type]
        principal=a_principal(MINE, Scope.EXPERIENCES_READ),
    )
    assert key.revoked_at is not None


async def test_a_stranger_cannot_revoke_someone_elses_key() -> None:
    """The failure that would matter: keys are minted by anyone, for free."""
    key = a_key(THEIRS)
    with pytest.raises(Forbidden):
        await routes.revoke_key(
            key_id=key.id,
            db=Session(key),  # type: ignore[arg-type]
            principal=a_principal(MINE, Scope.EXPERIENCES_READ, Scope.EXPERIENCES_WRITE),
        )
    assert key.revoked_at is None


async def test_an_admin_reaches_across_organizations() -> None:
    """Which is what ACTION_SCOPES['admin.keys'] has always named."""
    key = a_key(THEIRS)
    await routes.revoke_key(
        key_id=key.id,
        db=Session(key),  # type: ignore[arg-type]
        principal=a_principal(MINE, Scope.ADMIN),
    )
    assert key.revoked_at is not None


async def test_revoking_twice_keeps_the_first_timestamp() -> None:
    """The fact being recorded is when the key stopped working."""
    key = a_key(MINE)
    principal = a_principal(MINE, Scope.EXPERIENCES_READ)
    first = await routes.revoke_key(key_id=key.id, db=Session(key), principal=principal)  # type: ignore[arg-type]
    again = await routes.revoke_key(key_id=key.id, db=Session(key), principal=principal)  # type: ignore[arg-type]
    assert first["revoked_at"] == again["revoked_at"]
