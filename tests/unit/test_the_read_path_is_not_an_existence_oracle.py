"""Reading one Experience must not answer "does this id exist".

`GET /v1/experiences/{id}` answered 403 for an Experience that exists and is
not visible, and 404 for one that was never recorded. That is an existence
oracle over every private Experience in the corpus, available to anyone who
can call the API: ids are `exp_` plus a uuid4 and are not enumerable, but they
do not have to be enumerated -- they are handed to their owner in plain text at
record and they travel in logs, tickets and shared screenshots. Confirming one
is the attack, and the status code was the confirmation.

Decision 52 built the lineage traversal so an edge naming another tenant's
private Experience and an edge naming nothing at all produce byte-identical
output. That guarantee was partly cosmetic while a caller could put the same
id in the path instead and read the answer off the status line.

What is deliberately kept is the 403 *inside* one organization: a colleague who
cannot see a private Experience is better served by "this exists and you need
different permissions" than by being sent hunting for a typo. The rule is that
the distinction never crosses an organization, not that it disappears.
"""

from __future__ import annotations

from typing import Any

import pytest

from boobs_api.repositories import ExperienceRepository
from boobs_common.clock import now
from boobs_common.errors import Forbidden, NotFound
from boobs_domain.enums import ExperienceStatus, VerificationLevel, Visibility
from boobs_domain.protocols import Principal
from boobs_schemas.tables import Experience
from boobs_security.keys import Scope

READER = frozenset({Scope.EXPERIENCES_READ})
STRANGER = Principal(organization_id="org_theirs", agent_id="agt_theirs", scopes=READER)
COLLEAGUE = Principal(organization_id="org_mine", agent_id="agt_colleague", scopes=READER)
WRITER_ONLY = Principal(
    organization_id="org_theirs",
    agent_id="agt_writer",
    scopes=frozenset({Scope.EXPERIENCES_WRITE}),
)

NEVER_RECORDED = "exp_00000000-0000-4000-8000-000000000000"


def _experience(visibility: Visibility) -> Experience:
    return Experience(
        id="exp_secret",
        organization_id="org_mine",
        goal_statement="the thing nobody else may see",
        goal_intent="do_thing",
        tags=[],
        status=ExperienceStatus.CANDIDATE,
        verification_level=VerificationLevel.UNVERIFIED,
        visibility=visibility,
        latest_version=1,
        created_by="agt_owner",
        created_at=now(),
        updated_at=now(),
    )


class _Row:
    """The one SELECT `get` makes, answered with a row or with nothing."""

    def __init__(self, row: Experience | None) -> None:
        self._row = row

    async def execute(self, *_: object, **__: object) -> _Row:
        return self

    def scalar_one_or_none(self) -> Experience | None:
        return self._row


async def _read(principal: Principal, row: Experience | None, experience_id: str) -> str:
    """What the caller is told, as `ErrorName: sentence` -- the whole answer.

    Compared as one string on purpose: the error class decides the status code
    (main.py maps NotFound to 404 and Forbidden to 403) and the sentence is the
    body, so anything that differs between the two cases is the oracle back.
    """
    stub: Any = object()  # a read computes no embedding
    repository = ExperienceRepository(_Row(row), model=stub)  # type: ignore[arg-type]
    try:
        await repository.get(principal, experience_id)
    except (NotFound, Forbidden) as refusal:
        return f"{type(refusal).__name__}: {refusal}"
    return "read"


# ------------------------------------------------- across an organization


@pytest.mark.parametrize("visibility", [Visibility.PRIVATE, Visibility.ORGANIZATION])
async def test_invisible_and_never_recorded_are_the_same_answer(
    visibility: Visibility,
) -> None:
    """The claim decision 52 made about edges, made about the front door."""
    invisible = await _read(STRANGER, _experience(visibility), "exp_secret")
    absent = await _read(STRANGER, None, "exp_secret")

    assert invisible == absent
    assert invisible == "NotFound: experience exp_secret not found"


async def test_nothing_but_the_id_the_caller_typed_separates_the_two() -> None:
    """One real id and one that never existed, answered identically once the
    caller's own input is taken back out."""
    real = await _read(STRANGER, _experience(Visibility.PRIVATE), "exp_secret")
    fake = await _read(STRANGER, None, NEVER_RECORDED)
    assert real.replace("exp_secret", "ID") == fake.replace(NEVER_RECORDED, "ID")


async def test_a_public_experience_still_crosses_the_boundary() -> None:
    """The corpus is a shared brain; closing the oracle must not close that."""
    assert await _read(STRANGER, _experience(Visibility.PUBLIC), "exp_secret") == "read"


# ------------------------------------------------- inside one organization


async def test_a_colleague_is_still_told_it_exists() -> None:
    """403 earns its keep here: same tenant, wrong agent, real id. Sending them
    off to look for a typo would be a worse answer, and existence is not a fact
    their own organization is being told for the first time."""
    refused = await _read(COLLEAGUE, _experience(Visibility.PRIVATE), "exp_secret")
    assert refused == "Forbidden: not visible to this principal"


async def test_a_colleague_asking_for_nothing_still_gets_a_404() -> None:
    """Which is the point of keeping the 403: inside one organization the two
    answers are allowed to differ, and this pins that they do."""
    assert await _read(COLLEAGUE, None, NEVER_RECORDED) == (
        f"NotFound: experience {NEVER_RECORDED} not found"
    )


# ------------------------------------------------------------- the scope hole


async def test_a_key_without_the_read_scope_learns_nothing_either() -> None:
    """The scope check used to run after the row was fetched, so a write-only
    key got 403 for a real id and 404 for a fake one -- the same oracle, handed
    to the callers least entitled to it. Scope is answered without the row."""
    real = await _read(WRITER_ONLY, _experience(Visibility.PUBLIC), "exp_secret")
    fake = await _read(WRITER_ONLY, None, NEVER_RECORDED)
    assert real == fake
    assert real.startswith("Forbidden: missing scope")
