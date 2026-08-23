"""A retried execute must not buy a second sandbox run.

Executing is the only operation that spends real compute. A client that times
out after the commit and retries used to create a second Execution row and a
second real container -- silently, because both calls look successful. This
runs against real Postgres because the guarantee is a partial unique index,
and an index is not something a mock can be wrong about.
"""

from __future__ import annotations

import httpx
import pytest

from tests.helpers import auth, bootstrap, record_experience

pytestmark = [pytest.mark.integration]

DIGEST = "sha256:" + "ee" * 32

# Deliberately unlike anything else in the suite. Recall runs against a
# database shared by the whole session, so an Experience recorded here that
# reads like a real capability competes with the tests that assert about
# ranking -- and wins ties, because it has exactly as little evidence.
GOAL = "Stand in for a capability nobody recalls"
INTENT = "idempotency_probe"


async def execute(
    api: httpx.AsyncClient, key: str, experience_id: str, caller: str, **body: object
) -> httpx.Response:
    """Executing is rate limited per IP, and the whole suite shares one process.

    Each test presents its own forwarded address rather than sharing the one
    budget -- these are separate callers, which is exactly what the limit
    counts. Nothing about the limit itself is relaxed.
    """
    return await api.post(
        f"/v1/experiences/{experience_id}/execute",
        headers={**auth(key), "x-forwarded-for": caller},
        json=body,
    )


async def test_a_retry_returns_the_first_execution(api: httpx.AsyncClient) -> None:
    key = await bootstrap(api, "idem-org", "idem-agent")
    experience_id = await record_experience(api, key, GOAL, INTENT, DIGEST)

    first = await execute(api, key, experience_id, "10.0.0.1", idempotency_key="attempt-1")
    assert first.status_code == 202, first.text

    # Byte-identical retry, as a client that never saw the first response sends.
    second = await execute(api, key, experience_id, "10.0.0.1", idempotency_key="attempt-1")
    assert second.status_code in (200, 202), second.text
    assert second.json()["execution_id"] == first.json()["execution_id"]


async def test_a_different_key_is_a_different_run(api: httpx.AsyncClient) -> None:
    """The token scopes idempotency to one attempt, not to the experience.

    Deliberately running the same thing twice has to stay possible, or the
    feature would quietly cap every caller at one run per capability.
    """
    key = await bootstrap(api, "idem-distinct-org", "idem-distinct-agent")
    experience_id = await record_experience(api, key, GOAL, INTENT, DIGEST)

    first = await execute(api, key, experience_id, "10.0.0.2", idempotency_key="attempt-a")
    second = await execute(api, key, experience_id, "10.0.0.2", idempotency_key="attempt-b")
    third = await execute(api, key, experience_id, "10.0.0.2")  # no key at all

    ids = {response.json()["execution_id"] for response in (first, second, third)}
    assert len(ids) == 3


async def test_one_tenants_key_cannot_collide_with_anothers(api: httpx.AsyncClient) -> None:
    """The index is scoped per organization. If it were global, the second
    tenant would be handed the first tenant's execution id -- or refused a run
    because a stranger picked the same uuid."""
    mine = await bootstrap(api, "idem-mine-org", "idem-mine-agent")
    theirs = await bootstrap(api, "idem-theirs-org", "idem-theirs-agent")
    experience_id = await record_experience(api, mine, GOAL, INTENT, DIGEST)

    first = await execute(api, mine, experience_id, "10.0.0.3", idempotency_key="shared-token")
    second = await execute(api, theirs, experience_id, "10.0.0.4", idempotency_key="shared-token")

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["execution_id"] != second.json()["execution_id"]
