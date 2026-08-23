"""The demand signal, read at last -- and no longer holding anybody's words.

Decision 29 recorded misses and deliberately left nothing reading them, on the
grounds that recording is the irreversible half. Decision 49 stopped the raw
task text being one of the things recorded; decision 50 is the admin report
that reads what remains.

Both claims need a real database. "the column no longer holds what you typed"
is a claim about a schema, and "most wanted first" is a claim about an ORDER
BY -- neither survives being asserted against a mock.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import httpx
import pytest

from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]

# A customer name, in the shape somebody types one into a task by accident.
# The whole of decision 49 is the promise that this string reaches no column.
SECRET = "acme-industries-q4-margin"

# Deliberately unmatchable: the corpus is shared with every other integration
# test in the session, and a task that found something would record no miss.
WANTED_MOST = "flumox a zibbet into a quandle harness"
WANTED_SOME = "wrangle the snorkbat registry of a grimbly"
WANTED_ONCE = "polish a widgetoid until it thrums"


async def _bootstrap_org(api: httpx.AsyncClient, name: str) -> tuple[str, str]:
    """A key and the organization behind it.

    Misses are attributed to the recalling organization where one exists, and
    the fingerprint includes it -- so recalling under our own key is what makes
    this test's rows findable in a table every other test also writes to.
    """
    response = await api.post(
        "/v1/bootstrap",
        json={"organization": name, "agent": f"{name}-agent", "token": "test-bootstrap"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body["api_key"]), str(body["organization_id"])


async def _miss(api: httpx.AsyncClient, task: str, key: str, caller: str, times: int = 1) -> None:
    """Recall something nobody has recorded, `times` times, from one address."""
    for _ in range(times):
        response = await api.post(
            "/v1/experiences/recall",
            headers={**auth(key), "x-forwarded-for": caller},
            json={"task": task},
        )
        assert response.status_code == 200, response.text
        assert response.json()["matches"] == [], f"{task!r} was supposed to find nothing"


async def _settle(database_url: str, organization_id: str, occurrences: int) -> None:
    """Wait for the writes, which happen after the responses on purpose.

    Polled against the database rather than against the endpoint because the
    endpoint has a rate limit of its own, and spending it on a wait loop would
    make this test fail for the wrong reason.
    """
    dsn = database_url.replace("+asyncpg", "")
    total = 0
    for _ in range(100):
        connection = await asyncpg.connect(dsn)
        try:
            total = await connection.fetchval(
                "SELECT coalesce(sum(occurrences), 0) FROM recall_misses "
                "WHERE organization_id = $1",
                organization_id,
            )
        finally:
            await connection.close()
        if total >= occurrences:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"only {total} occurrences landed for {organization_id}")


async def _report(api: httpx.AsyncClient, key: str, caller: str, **params: int) -> dict[str, Any]:
    response = await api.get(
        "/v1/admin/recall-misses",
        headers={**auth(key), "x-forwarded-for": caller},
        params=params,
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


# ------------------------------------------------------------------- ranking


async def test_the_report_ranks_the_most_wanted_first(
    api: httpx.AsyncClient, database_url: str
) -> None:
    """Which is the entire reason to read this table rather than count it."""
    key, organization_id = await _bootstrap_org(api, "misses-ranking")
    admin = await bootstrap(api, "misses-ranking-admin", "reader", [Scope.ADMIN])

    await _miss(api, WANTED_MOST, key, "198.51.100.30", times=3)
    await _miss(api, WANTED_SOME, key, "198.51.100.30", times=2)
    await _miss(api, WANTED_ONCE, key, "198.51.100.30")
    await _settle(database_url, organization_id, occurrences=6)

    body = await _report(api, admin, "198.51.100.31", limit=100)
    ours = [m for m in body["misses"] if m["organization_id"] == organization_id]
    assert [m["occurrences"] for m in ours] == [3, 2, 1]
    # Three askings of one need are one row and a counter, not three rows.
    assert len(ours) == 3

    # The property, over every row rather than only ours: a page is sorted.
    everything = [m["occurrences"] for m in body["misses"]]
    assert everything == sorted(everything, reverse=True)


async def test_a_page_says_whether_there_is_another(
    api: httpx.AsyncClient, database_url: str
) -> None:
    """This table is designed to grow, so the report is capped by construction."""
    key, organization_id = await _bootstrap_org(api, "misses-paging")
    admin = await bootstrap(api, "misses-paging-admin", "reader", [Scope.ADMIN])

    await _miss(api, "carbonate the flimflam of a doohickey", key, "198.51.100.32", times=2)
    await _miss(api, "untangle a hoojamaflip from its sprocket", key, "198.51.100.32")
    await _settle(database_url, organization_id, occurrences=3)

    first = await _report(api, admin, "198.51.100.33", limit=1)
    assert len(first["misses"]) == 1
    assert first["next_offset"] == 1

    second = await _report(api, admin, "198.51.100.33", limit=1, offset=1)
    assert second["misses"] != first["misses"], "offset returned the same row again"


# ---------------------------------------------------------------------- auth


async def test_a_non_admin_cannot_read_anyone_else_s_demand(api: httpx.AsyncClient) -> None:
    """The failure that would matter: this is every tenant's demand in one list.

    An ordinary key holds read, write and run -- everything except admin --
    which is exactly the caller who must not be able to page through what
    other organizations have been asking for.
    """
    ordinary = await bootstrap(api, "misses-outsider", "outsider")
    refused = await api.get(
        "/v1/admin/recall-misses",
        headers={**auth(ordinary), "x-forwarded-for": "198.51.100.34"},
    )
    assert refused.status_code == 403, refused.text


async def test_no_credential_at_all_is_refused_too(api: httpx.AsyncClient) -> None:
    """Recall is keyless. Reading what everybody recalled is not."""
    anonymous = await api.get(
        "/v1/admin/recall-misses", headers={"x-forwarded-for": "198.51.100.35"}
    )
    assert anonymous.status_code == 401, anonymous.text


# ------------------------------------------------------------ what is stored


async def test_the_row_holds_nothing_the_caller_typed(
    api: httpx.AsyncClient, database_url: str
) -> None:
    """Decision 49, asserted against the real table rather than the model.

    A miss used to store the request verbatim and untruncated, from callers
    with no credential, and nothing read it. What is kept now is the canonical
    intent and the action and format labels `boobs_retrieval.intent` was able
    to recognize -- every one of which is a word written in our own source.
    """
    key, organization_id = await _bootstrap_org(api, "misses-retention")
    await _miss(api, f"deduplicate the {SECRET} zibbetgrams", key, "198.51.100.36")
    await _settle(database_url, organization_id, occurrences=1)

    connection = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    try:
        row = await connection.fetchrow(
            "SELECT * FROM recall_misses WHERE organization_id = $1", organization_id
        )
        columns = [
            name
            for (name,) in await connection.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'recall_misses'"
            )
        ]
    finally:
        await connection.close()

    # Not merely unwritten: there is nowhere left to write it.
    assert "task" not in columns
    # And nothing else on the row smuggled it in either.
    assert SECRET not in " ".join(str(value) for value in row.values())
    # What survives is the demand signal, in our vocabulary.
    assert row["terms"] == "deduplicate"
    assert row["intent"] == "deduplicate"
    assert row["occurrences"] == 1
