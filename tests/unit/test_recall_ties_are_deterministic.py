"""The same query must give the same recommendation, ties included.

Candidates are fetched in one batch with `WHERE id IN (...)` and no ORDER BY,
so the order rows come back in is whatever the planner and the buffer cache
produced that second. Sorting the survivors by score alone leaves equally
scored Experiences in that order -- which means the answer to an identical
query could change between two calls, on a corpus that had not changed. For a
product sold on reproducibility that is not a cosmetic problem.

Fetch order is simulated here by handing `_merge_and_rank` the same rows twice,
in both orders. Nothing else differs, so anything but an identical answer is
the database's row order leaking into the recommendation.
"""

from __future__ import annotations

from typing import Any

import pytest

from boobs_domain.protocols import RecallQuery
from boobs_retrieval import pipeline
from boobs_retrieval.intent import normalize
from boobs_schemas.tables import ExecutionStat, Experience, ExperienceVersion

QUERY = RecallQuery(task="convert a csv into json")
PARSED = normalize(QUERY.task)


class Db:
    """Returns one canned row set, in the order it was given."""

    def __init__(self, rows: list[tuple[Any, Any, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_: Any, **__: Any) -> Any:
        class Result:
            def all(inner_self) -> list[tuple[Any, Any, Any]]:  # noqa: N805
                return self._rows

        return Result()


def _pair(suffix: str, successful_runs: int) -> tuple[Any, Any, Any]:
    experience = Experience(
        id=f"exp_{suffix}",
        organization_id="org_ties",
        goal_statement="Convert a CSV file into a JSON array",
        goal_intent="csv_to_json",
        tags=[],
        status="candidate",
        visibility="public",
        latest_version=1,
        created_by="agt_ties",
    )
    version = ExperienceVersion(
        id=f"ver_{suffix}",
        experience_id=experience.id,
        organization_id="org_ties",
        version=1,
        artifact_id=f"art_{suffix}",
        command=["python", "/app/main.py"],
        requires_network=False,
        required_capabilities=[],
        search_text="csv to json",
        created_by="agt_ties",
    )
    stat = ExecutionStat(
        experience_version_id=version.id,
        experience_id=experience.id,
        successful_runs=successful_runs,
        failed_runs=0,
        success_rate=1.0,
        confidence=0.9,
        distinct_organizations=2,
        verification_level="proven",
        failure_modes={},
    )
    return version, experience, stat


async def _ranked(rows: list[tuple[Any, Any, Any]], scores: dict[str, float]) -> list[str]:
    outcome = await pipeline._merge_and_rank(
        Db(rows),  # type: ignore[arg-type]
        QUERY,
        PARSED,
        dict(scores),
        dict(scores),
    )
    return [match.experience_version_id for match in outcome.matches]


@pytest.mark.parametrize("reverse", [False, True])
async def test_identical_candidates_come_back_in_the_same_order(reverse: bool) -> None:
    """Two Experiences that score exactly alike, fetched in either order."""
    rows = [_pair("a", 4), _pair("b", 4)]
    scores = {"ver_a": 1.0, "ver_b": 1.0}

    order = await _ranked(list(reversed(rows)) if reverse else rows, scores)

    assert order == ["ver_a", "ver_b"], (
        "a tie was broken by the order the database happened to return: "
        f"{order} with rows reversed={reverse}"
    )


@pytest.mark.parametrize("reverse", [False, True])
async def test_a_tie_on_score_is_broken_by_proven_runs(reverse: bool) -> None:
    """And the tiebreaker is not arbitrary: between two equally good matches
    the better attested one is the better recommendation."""
    rows = [_pair("a", 1), _pair("b", 30)]
    scores = {"ver_a": 1.0, "ver_b": 1.0}

    order = await _ranked(list(reversed(rows)) if reverse else rows, scores)

    assert order[0] == "ver_b", order
