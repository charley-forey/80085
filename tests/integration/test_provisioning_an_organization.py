"""One organization, many people, one shared body of knowledge.

The primitive that was missing. `/v1/bootstrap` demands the root token and makes
a whole new organization; `/v1/keys` is self-serve and also makes a whole new
organization. Neither could add a second person to an existing one -- so an
organization's knowledge could never be shared by more than one caller, which is
the opposite of what this is for.

What is asserted here is the shape an enterprise actually deploys: an admin
provisions colleagues, everything they do is attributed to them individually,
and a verified answer reaches all of them.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import bootstrap_sync

pytestmark = [pytest.mark.integration]


@pytest.fixture
def admin(api_url: str) -> dict[str, Any]:
    """The one credential an organization gets from us, once."""
    from boobs_security.keys import Scope

    return bootstrap_sync(
        api_url, "acme-provisioning", "acme-admin", scopes=sorted({*Scope.ALL, Scope.ADMIN})
    )


def _auth(account: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['api_key']}"}


async def test_an_admin_provisions_colleagues_into_its_own_organization(
    api: httpx.AsyncClient, admin: dict[str, Any]
) -> None:
    head = _auth(admin)
    made = []
    for name in ("priya", "dev"):
        created = await api.post("/v1/agents", headers=head, json={"name": name})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["organization_id"] == admin["organization_id"], "key landed in another tenant"
        assert body["agent_id"] != admin["agent_id"]
        made.append(body)

    assert made[0]["agent_id"] != made[1]["agent_id"], "two people, two identities"
    assert made[0]["api_key"] != made[1]["api_key"]


async def test_a_provisioned_key_cannot_provision(
    api: httpx.AsyncClient, admin: dict[str, Any]
) -> None:
    """Admin is not inheritable.

    A team lead handing out keys must not hand out the ability to hand out keys.
    That is how an organization stops being able to say who can do what.
    """
    colleague = (await api.post("/v1/agents", headers=_auth(admin), json={"name": "priya"})).json()

    denied = await api.post(
        "/v1/agents",
        headers={"Authorization": f"Bearer {colleague['api_key']}"},
        json={"name": "someone-else"},
    )
    assert denied.status_code == 403, denied.text


async def test_colleagues_share_verified_knowledge_and_not_unverified(
    api: httpx.AsyncClient, admin: dict[str, Any]
) -> None:
    """The whole point of provisioning into one organization.

    Priya's agent halts and she answers in her own chat. That answer is hers
    until somebody says otherwise -- and once it is verified, Dev's agent
    inherits it without ever having asked.
    """
    head = _auth(admin)
    priya = (await api.post("/v1/agents", headers=head, json={"name": "priya"})).json()
    dev = (await api.post("/v1/agents", headers=head, json={"name": "dev"})).json()
    hers = {"Authorization": f"Bearer {priya['api_key']}"}
    his = {"Authorization": f"Bearer {dev['api_key']}"}

    need = "Whether our fiscal year starts in April or January for these reports"
    question_id = (await api.post("/v1/questions", headers=hers, json={"need": need})).json()[
        "question_id"
    ]
    answer_id = (
        await api.post(
            f"/v1/questions/{question_id}/answer",
            headers=hers,
            json={"body": "April. It has always been April.", "answered_by": "priya"},
        )
    ).json()["answer_id"]

    # Hers to act on immediately; not yet Dev's.
    assert (await api.post("/v1/questions", headers=hers, json={"need": need})).json()["answer"]
    assert (await api.post("/v1/questions", headers=his, json={"need": need})).json()[
        "answer"
    ] is None

    await api.post(f"/v1/answers/{answer_id}/verify", headers=head, json={"verified_by": "sam"})

    served = (await api.post("/v1/questions", headers=his, json={"need": need})).json()["answer"]
    assert served is not None, "a verified answer did not reach a colleague"
    assert served["body"].startswith("April")
