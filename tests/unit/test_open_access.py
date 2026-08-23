"""The access model: reading is free, writing is attributed.

Opening recall to the world is only safe because of two properties, and both
are asserted here rather than assumed:

* an anonymous caller can see public Experiences and nothing else
* only an *absent* credential is anonymous -- a bad one still fails

The third protection, that an unverified Experience is never recommended, is
covered by the ranking tests.
"""

from __future__ import annotations

import pytest

from boobs_api.deps import ANONYMOUS, get_principal_or_anonymous
from boobs_api.limits import RateLimited, Window
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
    sql = str(
        visibility_clause(ANONYMOUS).compile(compile_kwargs={"literal_binds": True})
    )
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
    theirs = str(
        visibility_clause(ANONYMOUS).compile(compile_kwargs={"literal_binds": True})
    )
    assert "org_real" in mine
    assert "org_real" not in theirs


# ------------------------------------------------------------------- the limits


def test_a_window_allows_up_to_the_limit_then_refuses() -> None:
    window = Window(limit=3, seconds=60, what="testing")
    for _ in range(3):
        window.check("1.2.3.4")
    with pytest.raises(RateLimited):
        window.check("1.2.3.4")


def test_callers_are_limited_separately() -> None:
    window = Window(limit=1, seconds=60, what="testing")
    window.check("1.1.1.1")
    window.check("2.2.2.2")  # must not raise
    with pytest.raises(RateLimited):
        window.check("1.1.1.1")


def test_the_message_says_what_to_do_about_it() -> None:
    window = Window(limit=1, seconds=60, what="recall")
    window.check("1.2.3.4")
    with pytest.raises(RateLimited) as caught:
        window.check("1.2.3.4")
    assert "recall" in str(caught.value)
    assert "open source" in str(caught.value)


def test_reading_is_the_most_generous_limit() -> None:
    """Whatever the numbers become, recall must stay the cheapest thing to do."""
    from boobs_api import limits

    per_second = lambda w: w.limit / w.seconds  # noqa: E731
    assert per_second(limits.RECALL) > per_second(limits.RECORD)
    assert per_second(limits.RECORD) > per_second(limits.EXECUTE)
