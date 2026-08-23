"""Who may hand out an hour of compute, and what the row says afterwards.

Decision 26 left tier grants as an `INSERT` an operator types, on the grounds
that approval an endpoint can perform is approval an attacker can request.
Decision 53 builds the endpoint and keeps the reasoning: the caller cannot ask
for a tier, they can only be given one by a key holding `admin`.

The refusal is the half worth pinning here. The rest -- that the row survives,
that `granted_tiers` then reads it back -- is asserted against a real database
in tests/integration/test_execution_tier_grants.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request

from boobs_api import routes
from boobs_common.clock import now
from boobs_common.config import ExecutionTier
from boobs_common.errors import Forbidden, NotFound
from boobs_domain.protocols import Principal
from boobs_schemas.api import GrantExecutionTiersRequest
from boobs_schemas.tables import Organization
from boobs_security.keys import Scope
from boobs_security.policy import TIER_GRANT_POLICY, granted_tiers

TARGET = "org_target"


class Session:
    """Answers `execute` from a prepared queue, in the order the handler asks."""

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.added: list[Any] = []

    async def execute(self, *_: Any, **__: Any) -> Any:
        value = self._results.pop(0)
        return SimpleNamespace(
            scalar_one=lambda: value,
            scalar_one_or_none=lambda: value,
            scalars=lambda: SimpleNamespace(first=lambda: value, all=lambda: value),
        )

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "client": ("10.0.0.9", 5000),
            "headers": [],
        }
    )


def _principal(*scopes: str) -> Principal:
    return Principal(organization_id="org_caller", agent_id="agt_caller", scopes=frozenset(scopes))


def _grant(*tiers: str, reason: str = "paid for the longer tier") -> GrantExecutionTiersRequest:
    return GrantExecutionTiersRequest(tiers=[ExecutionTier(t) for t in tiers], reason=reason)


def _organization() -> Organization:
    return Organization(id=TARGET, name="target", created_at=now())


@pytest.fixture(autouse=True)
def _no_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window is asserted over the router in test_open_access.py; here it
    would only mean feeding the fake session two more rows."""

    async def check(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(routes.limits.GRANT, "check", check)


async def test_an_ordinary_key_cannot_grant_itself_a_longer_run() -> None:
    """The whole reason tiers were not self-serve in the first place.

    A self-serve key holds read, write and run -- everything except admin --
    which is precisely the caller who must not be able to buy an hour of
    networked compute per execution by naming their own organization.
    """
    session = Session()
    with pytest.raises(Forbidden):
        await routes.grant_execution_tiers(
            organization_id="org_caller",
            request=_grant("extended"),
            http=_request(),
            db=session,  # type: ignore[arg-type]
            principal=_principal(
                Scope.EXPERIENCES_READ, Scope.EXPERIENCES_WRITE, Scope.EXECUTIONS_RUN
            ),
        )
    assert session.added == [], "a refused grant wrote a policy row anyway"


async def test_a_worker_key_cannot_grant_either() -> None:
    """A worker holds the one scope that talks to the lease, which is where
    tiers are actually spent. It still may not decide what they are worth."""
    with pytest.raises(Forbidden):
        await routes.grant_execution_tiers(
            organization_id=TARGET,
            request=_grant("standard"),
            http=_request(),
            db=Session(),  # type: ignore[arg-type]
            principal=_principal(Scope.WORKER),
        )


async def test_granting_names_an_organization_that_has_to_exist() -> None:
    """A typo becomes a 404, not a policy row nothing will ever read."""
    with pytest.raises(NotFound):
        await routes.grant_execution_tiers(
            organization_id="org_typo",
            request=_grant("standard"),
            http=_request(),
            db=Session(None),  # type: ignore[arg-type]
            principal=_principal(Scope.ADMIN),
        )


async def test_an_admin_grant_writes_the_tier_and_the_reason() -> None:
    """The row is the audit trail, so who and why live on it, not in a log."""
    session = Session(_organization(), None, [{"execution_tiers": ["standard"]}])
    answer = await routes.grant_execution_tiers(
        organization_id=TARGET,
        request=_grant("standard", reason="signed the compute addendum"),
        http=_request(),
        db=session,  # type: ignore[arg-type]
        principal=_principal(Scope.ADMIN),
    )
    (row,) = session.added
    assert row.organization_id == TARGET
    assert row.name == TIER_GRANT_POLICY
    assert row.rules["execution_tiers"] == ["standard"]
    assert row.rules["granted_by"] == "agt_caller"
    assert row.rules["reason"] == "signed the compute addendum"
    assert answer.granted == ["standard"]
    assert answer.effective == ["standard"]


async def test_a_grant_is_a_set_and_an_empty_one_takes_it_back() -> None:
    """Not a delta: repeating a request cannot accumulate an hour of compute,
    and there is a way back without an operator typing DELETE."""
    existing = SimpleNamespace(rules={"execution_tiers": ["standard", "extended"]})
    session = Session(_organization(), existing, [{"execution_tiers": []}])
    answer = await routes.grant_execution_tiers(
        organization_id=TARGET,
        request=_grant(reason="addendum lapsed"),
        http=_request(),
        db=session,  # type: ignore[arg-type]
        principal=_principal(Scope.ADMIN),
    )
    assert existing.rules["execution_tiers"] == []
    assert answer.granted == []
    assert answer.effective == []
    assert session.added == [], "an existing grant row was duplicated instead of replaced"


async def test_the_answer_reports_what_is_effective_not_only_what_it_wrote() -> None:
    """`granted_tiers` unions every policy row, so an operator's hand-written
    `INSERT` still grants. The endpoint owns one row; it says so."""
    session = Session(
        _organization(),
        None,
        [{"execution_tiers": ["standard"]}, {"execution_tiers": ["extended"]}],
    )
    answer = await routes.grant_execution_tiers(
        organization_id=TARGET,
        request=_grant("standard", reason="the ordinary grant"),
        http=_request(),
        db=session,  # type: ignore[arg-type]
        principal=_principal(Scope.ADMIN),
    )
    assert answer.granted == ["standard"]
    assert answer.effective == ["extended", "standard"]


def test_a_tier_nobody_defined_cannot_be_asked_for() -> None:
    """Validation is the enum, so the 422 names the three that exist."""
    with pytest.raises(ValueError):
        GrantExecutionTiersRequest(tiers=["forever"], reason="an hour is not enough")  # type: ignore[list-item]


def test_a_grant_needs_a_stated_reason() -> None:
    """An hour of compute approved with no cause is indistinguishable from a
    leaked admin key, and the row is the only place anyone would look."""
    with pytest.raises(ValueError):
        GrantExecutionTiersRequest(tiers=[ExecutionTier.EXTENDED], reason="ok")


def test_the_grant_row_is_what_the_lease_already_reads() -> None:
    """The endpoint writes the shape `granted_tiers` has always parsed; it did
    not invent a second one that the lease would have to learn."""
    assert granted_tiers([{"execution_tiers": ["standard", "extended"]}, {}, None]) == frozenset(
        {"standard", "extended"}
    )
