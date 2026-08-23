"""Two recordings racing for the same version number is a 409, not a 500.

`ExperienceRepository.create` reads `latest_version`, adds one, and writes the
new version back. Nothing holds the row in between, so two concurrent
recordings against the same Experience both read the same number and both try
to claim it. `uq_experience_version` catches the loser -- correctly -- and the
raw IntegrityError travelled all the way out as a 500 on a request that was
perfectly well formed.

`SqlEventStore.append`, in the same file, has the identical race on its own
sequence number and has always answered it with a Conflict. This is that
answer, applied to the other place that needed it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from boobs_api.repositories import ExperienceRepository
from boobs_common.errors import Conflict
from boobs_domain.protocols import Principal
from boobs_schemas.api import ArtifactIn, GoalIn, RecordExperienceRequest
from boobs_schemas.tables import Experience, ExperienceVersion

ORG = "org_versions"
PINNED = "registry.test/80085/demo@sha256:" + "ef" * 32


class Session:
    """Enough AsyncSession to reach the flush that collides."""

    def __init__(self, experience: Experience, collide: bool) -> None:
        self._rows: list[Any] = [None, experience]  # artifact lookup, then the parent
        self._collide = collide
        self.added: list[Any] = []

    async def execute(self, *_: Any, **__: Any) -> Any:
        row = self._rows.pop(0) if self._rows else None

        class Result:
            def scalar_one_or_none(self) -> Any:
                return row

            def scalar_one(self) -> Any:
                return row

        return Result()

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        if self._collide and any(isinstance(row, ExperienceVersion) for row in self.added):
            raise IntegrityError(
                "INSERT INTO experience_versions ...",
                {},
                Exception('duplicate key value violates unique constraint "uq_experience_version"'),
            )


class Allow:
    async def authorize(self, *_: Any, **__: Any) -> None: ...


class Constant:
    """The embedder, minus the model: what it returns does not matter here and
    loading fastembed to find that out would cost seconds."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]


def an_experience() -> Experience:
    return Experience(
        id="exp_versions",
        organization_id=ORG,
        goal_statement="Convert a CSV file into a JSON array",
        goal_intent="csv_to_json",
        tags=[],
        status="candidate",
        visibility="public",
        latest_version=1,
        created_by="agt_versions",
    )


def a_request() -> RecordExperienceRequest:
    return RecordExperienceRequest(
        experience_id="exp_versions",
        goal=GoalIn(statement="Convert a CSV file into a JSON array", intent="csv_to_json"),
        artifact=ArtifactIn(type="oci", reference=PINNED),
        command=["python", "/app/main.py"],
    )


async def _create(collide: bool) -> Any:
    experience = an_experience()
    repository = ExperienceRepository(
        Session(experience, collide),  # type: ignore[arg-type]
        policy=Allow(),  # type: ignore[arg-type]
        model=Constant(),
    )
    return await repository.create(
        Principal(organization_id=ORG, agent_id="agt_versions"), a_request()
    )


async def test_losing_the_race_for_a_version_number_is_a_conflict() -> None:
    with pytest.raises(Conflict) as raised:
        await _create(collide=True)

    # And the message says what to do about it, because the caller can: the
    # recording is still valid, it just needs the next number.
    assert "version 2" in str(raised.value)
    assert "record again" in str(raised.value)


async def test_winning_the_race_records_the_next_version() -> None:
    """The guard must not turn an ordinary second version into an error."""
    _experience, version = await _create(collide=False)
    assert version.version == 2
