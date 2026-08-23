"""A key must work on the request immediately after the one that minted it.

Five times this failed in CI and was written off as flake. It is not:
`get_db` commits in its dependency teardown, and FastAPI closes that exit
stack *after* `await response(...)`, so `POST /v1/keys` and `/v1/bootstrap`
handed back a credential whose row no other connection could see yet. The
caller used it, lost the race, and got `401 unknown api key`.

It hid well because the failure surfaces nowhere near its cause -- the
cleanest sighting was `assert 401 == 403` in a test about lease ownership,
which never reached the check it was written for and reads as an
authorisation bug in unrelated code.

Self-serve minting followed by immediate use is the *whole* onboarding path --
there is no signup, the key is the account -- so this broke first contact for
exactly the callers the product is trying to win, and did it at random.

The first two tests here are deterministic: rather than racing the window,
they reproduce the state the API is in while the key travels down the wire --
handler returned, teardown not yet run -- and ask a second connection whether
it can see the key. Both fail on the unfixed code every time. The last two are
the caller's own experience, hammered, because that is the shape the failures
actually took.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from starlette.requests import Request

from boobs_api import routes
from boobs_api.deps import get_db
from boobs_schemas.tables import ApiKey
from boobs_security.keys import hash_key
from tests.helpers import BOOTSTRAP_TOKEN, auth

pytestmark = [pytest.mark.integration]

ATTEMPTS = 20
# Nothing exists under this id. A key that authenticates gets 404; a key that
# does not gets 401, and that is the whole difference this test looks for.
NO_SUCH_EXECUTION = "/v1/executions/exec_" + "0" * 32


def a_request(caller: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/keys",
            "query_string": b"",
            "client": ("127.0.0.1", 5000),
            "headers": [(b"x-forwarded-for", caller.encode())],
        }
    )


async def visible_to_another_connection(key: str) -> bool:
    """Would a *different* pooled connection find this key right now?

    Which is the only question that matters, because the request that uses the
    key is not the request that minted it and does not share its transaction.
    """
    from boobs_schemas import db as database

    async with database.session() as other:
        found = await other.execute(select(ApiKey).where(ApiKey.key_hash == hash_key(key)))
        return found.scalar_one_or_none() is not None


async def test_the_key_is_committed_before_the_response_is_sent(db: Any) -> None:
    """The deterministic version of the race, at the exact point it happens.

    FastAPI closes the dependency exit stack *after* `await response(...)`, so
    `get_db`'s teardown commit runs when the caller already has the bytes. The
    state below -- handler returned, teardown not yet run -- is precisely the
    state the API is in while the key is travelling down the wire, and it is
    reproduced here rather than raced for.

    `db` is taken only to point the engine at the test database; the session
    under test is one the dependency makes for itself, exactly as a request
    would get.
    """
    request_scoped = get_db()
    session = await anext(request_scoped)
    minted = await routes.mint_key(http=a_request("203.0.113.200"), db=session, label="ordering")

    assert await visible_to_another_connection(minted["api_key"]), (
        "the caller has a key that no other connection can see: "
        "authenticating with it is a coin toss"
    )

    await request_scoped.aclose()  # the teardown that used to be the only commit


async def test_bootstrap_commits_before_the_response_is_sent(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bootstrap mints too, so it had the same race for the same reason."""
    from boobs_schemas.api import BootstrapRequest

    monkeypatch.setenv("BOOBS_BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)
    request_scoped = get_db()
    session = await anext(request_scoped)
    minted = await routes.bootstrap(
        request=BootstrapRequest(
            organization="ordering-org", agent="ordering-agent", token=BOOTSTRAP_TOKEN
        ),
        db=session,
    )

    assert await visible_to_another_connection(minted["api_key"])

    await request_scoped.aclose()


@pytest.fixture
async def second_client(api_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """A second connection, because one connection cannot lose this race.

    HTTP/1.1 keep-alive serializes requests on a socket, so a caller that
    reuses the same connection is accidentally protected: the server finishes
    the whole request -- teardown included -- before it reads the next one. A
    real caller opens a fresh connection, or several, and lands on whichever
    replica takes it. That caller is the one that gets the 401.
    """
    async with httpx.AsyncClient(base_url=api_url, timeout=60.0) as client:
        yield client


async def test_a_minted_key_authenticates_on_the_very_next_request(
    api: httpx.AsyncClient, second_client: httpx.AsyncClient
) -> None:
    async def mint_then_use(attempt: int) -> tuple[int, str]:
        # Minting is limited per address and these are separate callers, which
        # is exactly what the limit counts. Nothing about it is relaxed.
        minted = await api.post(
            "/v1/keys",
            params={"label": "race"},
            headers={"x-forwarded-for": f"203.0.113.{attempt}"},
        )
        assert minted.status_code == 201, minted.text
        used = await second_client.get(NO_SUCH_EXECUTION, headers=auth(minted.json()["api_key"]))
        return used.status_code, used.text

    # Concurrently, so the window between "response sent" and "transaction
    # committed" is occupied by somebody.
    outcomes = await asyncio.gather(*(mint_then_use(attempt) for attempt in range(ATTEMPTS)))
    refused = [outcome for outcome in outcomes if outcome[0] != 404]
    assert not refused, f"keys minted a moment earlier were refused: {refused}"


async def test_a_bootstrapped_key_authenticates_on_the_very_next_request(
    api: httpx.AsyncClient, second_client: httpx.AsyncClient
) -> None:
    """Bootstrap mints too, so it had the same race for the same reason."""

    async def bootstrap_then_use(attempt: int) -> tuple[int, str]:
        minted = await api.post(
            "/v1/bootstrap",
            json={
                "organization": f"race-org-{attempt}",
                "agent": "race-agent",
                "token": BOOTSTRAP_TOKEN,
            },
        )
        assert minted.status_code == 201, minted.text
        used = await second_client.get(NO_SUCH_EXECUTION, headers=auth(minted.json()["api_key"]))
        return used.status_code, used.text

    outcomes = await asyncio.gather(*(bootstrap_then_use(attempt) for attempt in range(ATTEMPTS)))
    refused = [outcome for outcome in outcomes if outcome[0] != 404]
    assert not refused, f"keys bootstrapped a moment earlier were refused: {refused}"
