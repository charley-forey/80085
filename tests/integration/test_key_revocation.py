"""Revocation, over HTTP and against a real database.

docs/security.md has always said keys are "revocable". `revoked_at` was
checked at authentication and set by nothing, so revoking one meant an UPDATE
run by hand against production.

Both halves are asserted here: that a revoked key actually stops working on
the next request, and that revocation cannot be aimed at somebody else's key.
The second is the one that matters -- keys mint anonymously, so without it any
caller could take out any other caller's credential for the price of an id.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap

pytestmark = [pytest.mark.integration]

NO_SUCH_EXECUTION = "/v1/executions/exec_" + "0" * 32


async def mint(api: httpx.AsyncClient, caller: str) -> dict[str, Any]:
    """A self-serve key, from its own address so each test has its own budget."""
    response = await api.post(
        "/v1/keys", params={"label": "revocation"}, headers={"x-forwarded-for": caller}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def authenticates(api: httpx.AsyncClient, key: str) -> bool:
    """404 means the key was accepted and the execution simply is not there."""
    return (await api.get(NO_SUCH_EXECUTION, headers=auth(key))).status_code == 404


async def test_a_revoked_key_stops_working_on_the_next_request(api: httpx.AsyncClient) -> None:
    minted = await mint(api, "198.51.100.10")
    assert await authenticates(api, minted["api_key"])

    revoked = await api.post(f"/v1/keys/{minted['key_id']}/revoke", headers=auth(minted["api_key"]))
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None

    refused = await api.get(NO_SUCH_EXECUTION, headers=auth(minted["api_key"]))
    assert refused.status_code == 401, refused.text
    assert "revoked" in refused.json()["detail"]


async def test_a_stranger_cannot_revoke_someone_elses_key(api: httpx.AsyncClient) -> None:
    victim = await mint(api, "198.51.100.11")
    attacker = await mint(api, "198.51.100.12")

    refused = await api.post(
        f"/v1/keys/{victim['key_id']}/revoke", headers=auth(attacker["api_key"])
    )
    assert refused.status_code == 403, refused.text
    assert await authenticates(api, victim["api_key"]), "the victim's key was revoked anyway"


async def test_an_admin_reaches_across_organizations(api: httpx.AsyncClient) -> None:
    victim = await mint(api, "198.51.100.13")
    admin = await bootstrap(api, "revoke-admin-org", "revoke-admin", [Scope.ADMIN])

    revoked = await api.post(f"/v1/keys/{victim['key_id']}/revoke", headers=auth(admin))
    assert revoked.status_code == 200, revoked.text
    assert not await authenticates(api, victim["api_key"])


async def test_revoking_a_key_that_does_not_exist_is_not_found(api: httpx.AsyncClient) -> None:
    caller = await mint(api, "198.51.100.14")
    missing = await api.post(
        "/v1/keys/key_" + "0" * 32 + "/revoke", headers=auth(caller["api_key"])
    )
    assert missing.status_code == 404, missing.text
