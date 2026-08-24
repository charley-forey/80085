"""The access model: reading is free, writing is attributed.

Opening recall to the world is only safe because of two properties, and both
are asserted here rather than assumed:

* an anonymous caller can see public Experiences and nothing else
* only an *absent* credential is anonymous -- a bad one still fails

The third protection, that an unverified Experience is never recommended, is
covered by the ranking tests.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from boobs_api import routes
from boobs_api.deps import ANONYMOUS, get_principal_or_anonymous
from boobs_api.limits import RateLimited, Window, client_ip
from boobs_common.errors import Unauthorized
from boobs_domain.enums import Visibility
from boobs_domain.protocols import Principal
from boobs_retrieval.pipeline import visibility_clause
from boobs_security.keys import Scope

# --------------------------------------------------------------- the anonymous


def test_anonymous_may_only_read() -> None:
    assert ANONYMOUS.scopes == frozenset({Scope.EXPERIENCES_READ})
    for forbidden in (Scope.EXPERIENCES_WRITE, Scope.EXECUTIONS_RUN, Scope.ADMIN):
        assert forbidden not in ANONYMOUS.scopes


def test_anonymous_belongs_to_no_real_organization() -> None:
    """The whole security model rests on this id matching nothing."""
    assert ANONYMOUS.organization_id == "org_anonymous"
    assert not ANONYMOUS.organization_id.startswith("org_2")  # not a generated id


def test_anonymous_sees_public_experiences_and_nothing_else() -> None:
    """Render the SQL predicate and read what it actually permits.

    visibility_clause is the only thing standing between an anonymous caller
    and someone else's private work, so it is asserted directly rather than
    through a route.
    """
    sql = str(visibility_clause(ANONYMOUS).compile(compile_kwargs={"literal_binds": True}))
    # Public is allowed outright.
    assert f"visibility = '{Visibility.PUBLIC.value}'" in sql.replace('"', "")
    # Everything else is gated on owning the row, and nobody owns org_anonymous.
    assert "org_anonymous" in sql


# ------------------------------------------------------------ absent vs broken


async def test_absent_credential_is_anonymous() -> None:
    assert await get_principal_or_anonymous(db=None, authorization=None) is ANONYMOUS  # type: ignore[arg-type]
    assert await get_principal_or_anonymous(db=None, authorization="   ") is ANONYMOUS  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "header",
    [
        "Bearer sk_80085_obviously-not-real",  # well-formed, unknown
        "Bearer nonsense",  # malformed
        "sk_80085_missing-the-scheme",
        "Basic dXNlcjpwYXNz",
    ],
)
async def test_a_bad_credential_is_rejected_not_downgraded(header: str) -> None:
    """Silently treating a bad key as anonymous would turn an expired
    credential into a permission change nobody asked for, and would hide key
    rotation bugs from whoever has to debug them."""
    with pytest.raises(Unauthorized):
        await get_principal_or_anonymous(db=_NoRows(), authorization=header)  # type: ignore[arg-type]


class _NoRows:
    """A session that finds no key, so lookup fails the way it would live."""

    async def execute(self, *_: object, **__: object) -> _NoRows:
        return self

    def scalar_one_or_none(self) -> None:
        return None


# ------------------------------------------------------------------- contribute


def test_recording_defaults_to_public() -> None:
    """A shared brain whose contributions default to invisible is not shared."""
    from boobs_schemas.api import ArtifactIn, GoalIn, RecordExperienceRequest

    request = RecordExperienceRequest(
        goal=GoalIn(statement="do the thing", intent="thing"),
        artifact=ArtifactIn(reference="registry/x@sha256:" + "a" * 64),
    )
    assert request.visibility is Visibility.PUBLIC


def test_a_contributor_can_still_keep_something_private() -> None:
    from boobs_schemas.api import ArtifactIn, GoalIn, RecordExperienceRequest

    request = RecordExperienceRequest(
        goal=GoalIn(statement="do the thing", intent="thing"),
        artifact=ArtifactIn(reference="registry/x@sha256:" + "a" * 64),
        visibility=Visibility.PRIVATE,
    )
    assert request.visibility is Visibility.PRIVATE


def test_a_private_experience_is_invisible_to_anonymous() -> None:
    """The other half of public-by-default: opting out must actually work."""
    owner = Principal(organization_id="org_real", agent_id="agt_real")
    mine = str(visibility_clause(owner).compile(compile_kwargs={"literal_binds": True}))
    theirs = str(visibility_clause(ANONYMOUS).compile(compile_kwargs={"literal_binds": True}))
    assert "org_real" in mine
    assert "org_real" not in theirs


# ------------------------------------------------------------------- the limits


class Counters:
    """The rate_limits table, minus Postgres.

    The real limiter is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`,
    so a dict keyed the same way does the same arithmetic and these stay unit
    tests. That the SQL means what this says it means -- including across
    processes, which is the whole point of moving the counter into the
    database -- is asserted in tests/integration/test_rate_limits.py.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, int], int] = {}

    async def execute(self, _: Any, params: dict[str, Any] | None = None) -> Any:
        if params is None:  # the SET LOCAL that keeps this commit off the disk
            return None
        row = (params["bucket"], params["window_start"])
        self.rows[row] = self.rows.get(row, 0) + 1
        return SimpleNamespace(scalar_one=lambda: self.rows[row])

    async def commit(self) -> None: ...


async def test_a_window_allows_up_to_the_limit_then_refuses() -> None:
    window, db = Window(limit=3, seconds=60, what="testing"), Counters()
    for _ in range(3):
        await window.check(db, "1.2.3.4")  # type: ignore[arg-type]
    with pytest.raises(RateLimited):
        await window.check(db, "1.2.3.4")  # type: ignore[arg-type]


async def test_callers_are_limited_separately() -> None:
    window, db = Window(limit=1, seconds=60, what="testing"), Counters()
    await window.check(db, "1.1.1.1")  # type: ignore[arg-type]
    await window.check(db, "2.2.2.2")  # type: ignore[arg-type] - must not raise
    with pytest.raises(RateLimited):
        await window.check(db, "1.1.1.1")  # type: ignore[arg-type]


async def test_limits_of_different_lengths_do_not_share_a_counter() -> None:
    """One table holds every window now, so the name has to be part of the key."""
    db, ip = Counters(), "1.2.3.4"
    await Window(limit=1, seconds=60, what="recall").check(db, ip)  # type: ignore[arg-type]
    await Window(limit=1, seconds=3600, what="minting").check(db, ip)  # type: ignore[arg-type]
    assert len(db.rows) == 2


async def test_the_message_says_what_to_do_about_it() -> None:
    window, db = Window(limit=1, seconds=60, what="recall"), Counters()
    await window.check(db, "1.2.3.4")  # type: ignore[arg-type]
    with pytest.raises(RateLimited) as caught:
        await window.check(db, "1.2.3.4")  # type: ignore[arg-type]
    assert "recall" in str(caught.value)
    assert "open source" in str(caught.value)


def test_reading_is_the_most_generous_limit() -> None:
    """Whatever the numbers become, recall must stay the cheapest thing to do."""
    from boobs_api import limits

    per_second = lambda w: w.limit / w.seconds  # noqa: E731
    assert per_second(limits.RECALL) > per_second(limits.RECORD)
    assert per_second(limits.RECORD) > per_second(limits.EXECUTE)
    assert per_second(limits.RECALL) > per_second(limits.VERIFY)


# Guarded by BOOBS_BOOTSTRAP_TOKEN rather than by a window; and revocation is
# an authenticated, idempotent write against the caller's own organization --
# throttling it would slow down burning a leaked key, which is the one write
# that should never be slow.
UNLIMITED = {"/v1/bootstrap", "/v1/keys/{key_id}/revoke"}


def test_every_write_path_is_rate_limited() -> None:
    """verify_execution had no limiter at all while every sibling had one.

    It is the endpoint that turns a finished run into evidence, and evidence
    is the entire product, so it was the wrong one to leave open. Asserted
    over the router rather than over a list, because the next write endpoint
    added should have to answer this question too.
    """
    unlimited = [
        route.path
        for route in routes.router.routes
        if "POST" in getattr(route, "methods", set())
        and route.path not in UNLIMITED
        and "limits." not in inspect.getsource(route.endpoint)  # type: ignore[attr-defined]
    ]
    assert not unlimited, f"write paths with no rate limit: {unlimited}"


def test_every_admin_route_is_rate_limited() -> None:
    """The check above looks at POSTs, and the admin surface is not all POSTs.

    `GET /v1/admin/recall-misses` pages through every gap in the corpus, which
    is a cheap query and an expensive thing to let a leaked admin key hoover
    up at speed. Asked over the prefix rather than the one route, so the next
    admin read has to answer it too.
    """
    unlimited = [
        route.path
        for route in routes.router.routes
        if route.path.startswith("/v1/admin")
        and route.path not in UNLIMITED
        and "limits." not in inspect.getsource(route.endpoint)  # type: ignore[attr-defined]
    ]
    assert not unlimited, f"admin paths with no rate limit: {unlimited}"


# --------------------------------------------------------- who the caller is


def _request(**headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "client": ("10.0.0.9", 5000),
            "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_a_caller_cannot_choose_their_own_rate_limit_bucket() -> None:
    """X-Forwarded-For is appended to by each hop, so everything to the left
    of the last entry is whatever the caller sent. Reading the leftmost value
    let anyone mint unlimited keys by varying one header -- and minting is the
    root of the Sybil tree: a fresh organization per key, no identity."""
    assert client_ip(_request(x_forwarded_for="1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_a_direct_caller_is_their_socket_address() -> None:
    assert client_ip(_request()) == "10.0.0.9"


def test_the_bucket_is_the_address_the_edge_vouches_for() -> None:
    """Railway sets X-Real-IP at the edge and documents it as the client's
    address. The last X-Forwarded-For entry changed per connection in
    production, so every limit was per-connection: a caller reconnecting for
    each request was never limited at all. X-Real-IP wins when present."""
    assert (
        client_ip(_request(x_real_ip="198.51.100.4", x_forwarded_for="1.2.3.4, 10.0.0.2"))
        == "198.51.100.4"
    )
    assert (
        client_ip(_request(x_real_ip="  ", x_forwarded_for="1.2.3.4, 203.0.113.7")) == "203.0.113.7"
    )


# ------------------------------------------------------- minting without asking

# A write needs a key, and there is no signup to send anyone to, so the local
# server mints one rather than stopping to ask a question with no answer. What
# these pin down is where it must NOT do that.


class _Ctx:
    """Stands in for a hosted request, which arrives with headers."""

    def __init__(self, **headers: str) -> None:
        self.headers = headers


@pytest.fixture()
def mcp(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    from boobs_mcp import server

    monkeypatch.setattr(server, "KEY_FILE", tmp_path / "key")
    monkeypatch.delenv("BOOBS_API_KEY", raising=False)
    minted: list[int] = []

    async def fake_mint() -> str:
        minted.append(1)
        server.KEY_FILE.write_text("sk_80085_minted", encoding="utf-8")
        return "sk_80085_minted"

    monkeypatch.setattr(server, "_mint", fake_mint)
    return server, minted


async def test_a_reader_is_never_given_a_credential(mcp) -> None:  # type: ignore[no-untyped-def]
    """The whole point of keyless recall: asking a question costs nothing."""
    server, minted = mcp
    assert await server._api_key(None, required=False) is None
    assert minted == []


async def test_a_local_write_mints_rather_than_asking(mcp) -> None:  # type: ignore[no-untyped-def]
    server, minted = mcp
    assert await server._api_key(None) == "Bearer sk_80085_minted"
    assert minted == [1]


async def test_it_only_mints_once(mcp) -> None:  # type: ignore[no-untyped-def]
    """Remembered on disk, so contributing does not mint a key per call."""
    server, minted = mcp
    assert await server._api_key(None) == "Bearer sk_80085_minted"
    assert await server._api_key(None) == "Bearer sk_80085_minted"
    assert minted == [1]


async def test_the_hosted_server_never_mints(mcp) -> None:  # type: ignore[no-untyped-def]
    """It is multi-tenant: a key minted there would file every caller's
    contributions under whoever connected first."""
    server, minted = mcp
    with pytest.raises(server.MissingKey):
        await server._api_key(_Ctx(host="mcp.80085.ai"))
    assert minted == []


async def test_the_hosted_server_forwards_the_caller_key(mcp) -> None:  # type: ignore[no-untyped-def]
    server, minted = mcp
    ctx = _Ctx(authorization="Bearer sk_80085_theirs")
    assert await server._api_key(ctx) == "Bearer sk_80085_theirs"
    assert minted == []


async def test_the_dead_end_tells_you_how_to_leave_it(mcp) -> None:  # type: ignore[no-untyped-def]
    """An agent that reads this error can fix it without a human."""
    server, _ = mcp
    with pytest.raises(server.MissingKey) as caught:
        await server._api_key(_Ctx(host="mcp.80085.ai"))
    message = str(caught.value)
    assert "/v1/keys" in message
    assert "no signup" in message.lower()
