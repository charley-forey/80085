"""Who may read the demand report, and in what order it comes back.

The table `recall_misses` is every tenant's unmet demand in one list, and the
rows are not visibility-filtered the way Experiences are -- there is nothing to
filter, because a miss belongs to whoever asked and mostly to nobody. So the
only thing standing between one organization's demand and another's is the
scope check asserted here.

End to end, against a real database and a real ORDER BY, in
tests/integration/test_recall_misses_report.py.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Select
from starlette.requests import Request

from boobs_api import routes
from boobs_common.clock import now
from boobs_common.errors import Forbidden
from boobs_domain.protocols import Principal
from boobs_schemas.tables import RecallMiss
from boobs_security.keys import Scope


class Session:
    """Enough of an AsyncSession for the limiter and one SELECT.

    The limiter's own arithmetic is asserted in test_open_access.py; here it
    only has to not get in the way, which is why its statements are counted
    rather than modelled.
    """

    def __init__(self, *rows: RecallMiss) -> None:
        self.rows = list(rows)
        self.selected: Select[Any] | None = None
        self.hits = 0

    async def execute(self, statement: Any, params: Any = None) -> Any:
        if isinstance(statement, Select):
            self.selected = statement
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))
        if "SELECT" in str(statement):  # the limiter's previous-window read
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        self.hits += 1
        return SimpleNamespace(scalar_one=lambda: self.hits)

    async def commit(self) -> None: ...


def a_miss(occurrences: int, intent: str = "unknown", terms: str = "") -> RecallMiss:
    timestamp = now() - timedelta(days=occurrences)
    return RecallMiss(
        id=f"miss_{intent}_{occurrences}",
        fingerprint=f"{intent}{occurrences}",
        organization_id=None,
        terms=terms,
        intent=intent,
        environment={"os": "linux"},
        constraints={"network": False},
        candidates=40,
        cleared=0,
        best_score=0.29,
        occurrences=occurrences,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    )


def a_principal(*scopes: str) -> Principal:
    return Principal(organization_id="org_caller", agent_id="agt_caller", scopes=frozenset(scopes))


async def read(session: Session, principal: Principal, limit: int = 20, offset: int = 0) -> Any:
    """Call the handler the way FastAPI would.

    `limit` and `offset` are passed explicitly because calling a route
    function directly hands it the `Query(...)` markers rather than their
    defaults, and a test that quietly paged by a Query object would be
    asserting nothing at all.
    """
    return await routes.read_recall_misses(
        http=a_request(),
        db=session,  # type: ignore[arg-type]
        principal=principal,
        limit=limit,
        offset=offset,
    )


def a_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/admin/recall-misses",
            "query_string": b"",
            "client": ("10.0.0.9", 5000),
            "headers": [],
        }
    )


async def test_an_ordinary_key_is_refused() -> None:
    """Read, write and run -- everything except admin -- and still no."""
    with pytest.raises(Forbidden):
        await read(
            Session(),
            a_principal(Scope.EXPERIENCES_READ, Scope.EXPERIENCES_WRITE, Scope.EXECUTIONS_RUN),
        )


async def test_a_worker_key_is_refused_too() -> None:
    """A worker holds a credential this codebase hands to a machine on a host
    that is not ours. It leases jobs; it does not read the corpus's gaps."""
    with pytest.raises(Forbidden):
        await read(Session(), a_principal(Scope.WORKER))


async def test_an_admin_reads_it() -> None:
    session = Session(a_miss(9, "pdf_to_json", "convert json pdf"), a_miss(2))
    response = await read(session, a_principal(Scope.ADMIN))

    assert [m.occurrences for m in response.misses] == [9, 2]
    assert response.misses[0].terms == "convert json pdf"
    # The pair that makes a miss actionable: forty near-candidates means the
    # ranking is too strict, an empty corpus means there is a hole.
    assert response.misses[0].candidates == 40
    assert response.misses[0].best_score == 0.29


async def test_it_is_ranked_by_demand() -> None:
    """Asserted on the statement, because sorting is the database's job.

    A fake session can return rows in any order it likes and prove nothing, so
    what is checked is the ORDER BY actually sent.
    """
    session = Session(a_miss(1))
    await read(session, a_principal(Scope.ADMIN))

    assert session.selected is not None
    sql = str(session.selected.compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY recall_misses.occurrences DESC" in sql
    # Deterministic within a tie, so a page boundary cannot repeat or skip.
    assert "recall_misses.id" in sql.split("ORDER BY")[1]


async def test_a_full_page_says_there_is_another() -> None:
    """One row beyond the page is fetched, so "is there more" costs no COUNT."""
    session = Session(a_miss(3), a_miss(2), a_miss(1))
    response = await read(session, a_principal(Scope.ADMIN), limit=2)

    assert [m.occurrences for m in response.misses] == [3, 2]
    assert response.next_offset == 2


async def test_the_last_page_says_so() -> None:
    session = Session(a_miss(3), a_miss(2))
    response = await read(session, a_principal(Scope.ADMIN), limit=2)

    assert response.next_offset is None


def test_the_report_returns_no_free_text() -> None:
    """The other half of decision 49: what is not stored is also not served.

    `fingerprint` is deliberately absent too. It is a sha256 over the
    normalized task, so it recovers nothing -- but it does confirm a guess,
    and a demand report has no use for one.
    """
    from boobs_schemas.api import RecallMissOut

    returned = set(RecallMissOut.model_fields)
    assert "task" not in returned
    assert "fingerprint" not in returned
    # Both of the fields that do describe the need come from closed tables in
    # boobs_retrieval.intent, never from what the caller typed.
    assert {"intent", "terms"} <= returned
