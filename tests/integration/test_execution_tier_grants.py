"""Granting an execution tier, over HTTP and against a real database.

Decision 26 shipped tiers with no way to grant one: an operator ran an
`INSERT` into `policies`, because approval an endpoint can perform is approval
an attacker can request. Decision 53 builds the endpoint under `admin` and
keeps that sentence true -- nobody can ask for a tier for themselves.

What needs a real database here is the round trip: the row this writes has to
be the row `granted_tiers` already reads, through JSONB and back, or the grant
is a 200 that changes nothing at lease time.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap

pytestmark = [pytest.mark.integration]

ROUTE = "/v1/admin/organizations/{organization_id}/execution-tiers"


async def _organization(api: httpx.AsyncClient, name: str) -> str:
    response = await api.post(
        "/v1/bootstrap",
        json={"organization": name, "agent": f"{name}-agent", "token": "test-bootstrap"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["organization_id"])


async def _grant(
    api: httpx.AsyncClient,
    key: str,
    caller: str,
    organization_id: str,
    tiers: list[str],
    reason: str = "signed the compute addendum",
) -> httpx.Response:
    return await api.post(
        ROUTE.format(organization_id=organization_id),
        headers={**auth(key), "x-forwarded-for": caller},
        json={"tiers": tiers, "reason": reason},
    )


def _body(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    return dict(response.json())


# ---------------------------------------------------------------------- auth


async def test_an_ordinary_key_cannot_grant_itself_an_hour_of_compute(
    api: httpx.AsyncClient,
) -> None:
    """The failure that would matter, and the whole reason decision 26 left
    this to an operator: an ordinary key holds read, write and run, which is
    exactly the caller who must not be able to buy `extended` for itself."""
    ordinary = await bootstrap(api, "tier-outsider", "outsider")
    mine = await _organization(api, "tier-outsider-target")
    refused = await _grant(api, ordinary, "198.51.100.70", mine, ["extended"])
    assert refused.status_code == 403, refused.text


async def test_no_credential_at_all_is_refused(api: httpx.AsyncClient) -> None:
    target = await _organization(api, "tier-anonymous-target")
    anonymous = await api.post(
        ROUTE.format(organization_id=target),
        headers={"x-forwarded-for": "198.51.100.71"},
        json={"tiers": ["standard"], "reason": "no credential at all"},
    )
    assert anonymous.status_code == 401, anonymous.text


# -------------------------------------------------------------------- grants


async def test_an_admin_grant_survives_the_round_trip(api: httpx.AsyncClient) -> None:
    """`effective` is computed by re-reading `policies` with the same function
    the lease uses, so a 200 here means the tier is genuinely spendable."""
    admin = await bootstrap(api, "tier-admin", "granter", [Scope.ADMIN])
    target = await _organization(api, "tier-target")

    granted = _body(await _grant(api, admin, "198.51.100.72", target, ["standard"]))
    assert granted["organization_id"] == target
    assert granted["granted"] == ["standard"]
    assert granted["effective"] == ["standard"]
    assert granted["reason"] == "signed the compute addendum"
    assert granted["granted_by"].startswith("agt_")


async def test_a_grant_is_a_set_and_replacing_it_takes_a_tier_back(
    api: httpx.AsyncClient,
) -> None:
    """Not a delta and not append-only: an hour of compute must be revocable
    without an operator typing DELETE against production, and repeating a
    request must not accumulate anything."""
    admin = await bootstrap(api, "tier-set-admin", "granter", [Scope.ADMIN])
    target = await _organization(api, "tier-set-target")

    assert _body(await _grant(api, admin, "198.51.100.73", target, ["standard"]))["effective"] == [
        "standard"
    ]
    both = _body(await _grant(api, admin, "198.51.100.73", target, ["extended", "standard"]))
    assert both["effective"] == ["extended", "standard"]
    # Idempotent: the same request again is the same state, not more of it.
    again = _body(await _grant(api, admin, "198.51.100.73", target, ["extended", "standard"]))
    assert again["effective"] == ["extended", "standard"]

    revoked = _body(
        await _grant(api, admin, "198.51.100.73", target, [], reason="the addendum lapsed")
    )
    assert revoked["granted"] == []
    assert revoked["effective"] == []


async def test_a_grant_reaches_one_organization_and_no_other(
    api: httpx.AsyncClient,
) -> None:
    """The path names the tenant, and there is no parameter that widens it."""
    admin = await bootstrap(api, "tier-scope-admin", "granter", [Scope.ADMIN])
    lucky = await _organization(api, "tier-scope-lucky")
    bystander = await _organization(api, "tier-scope-bystander")

    _body(await _grant(api, admin, "198.51.100.74", lucky, ["extended"]))
    assert _body(await _grant(api, admin, "198.51.100.74", bystander, []))["effective"] == []


# ---------------------------------------------------------------- refusals


async def test_granting_to_an_organization_that_does_not_exist_is_not_found(
    api: httpx.AsyncClient,
) -> None:
    """A typo becomes a 404, not a policy row nothing will ever read."""
    admin = await bootstrap(api, "tier-typo-admin", "granter", [Scope.ADMIN])
    missing = await _grant(api, admin, "198.51.100.75", "org_" + "0" * 32, ["standard"])
    assert missing.status_code == 404, missing.text


async def test_a_tier_nobody_defined_is_refused(api: httpx.AsyncClient) -> None:
    admin = await bootstrap(api, "tier-unknown-admin", "granter", [Scope.ADMIN])
    target = await _organization(api, "tier-unknown-target")
    refused = await _grant(api, admin, "198.51.100.76", target, ["forever"])
    assert refused.status_code == 422, refused.text


async def test_a_grant_with_no_stated_reason_is_refused(api: httpx.AsyncClient) -> None:
    """The row is the audit trail; an empty reason makes it useless."""
    admin = await bootstrap(api, "tier-reason-admin", "granter", [Scope.ADMIN])
    target = await _organization(api, "tier-reason-target")
    refused = await _grant(api, admin, "198.51.100.77", target, ["extended"], reason="")
    assert refused.status_code == 422, refused.text
