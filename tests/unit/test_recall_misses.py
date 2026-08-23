"""A recall that finds nothing is the one row this system cannot backfill.

Two properties, and the second matters more than the first: a miss is recorded
exactly once and only when there was one, and failing to record it never costs
the caller their recall.
"""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks

from boobs_api import misses, routes
from boobs_domain.entities import Evidence, RecallCandidate
from boobs_domain.enums import Compatibility, Recommendation
from boobs_domain.protocols import Principal, RecallQuery
from boobs_retrieval.intent import normalize
from boobs_retrieval.pipeline import RecallOutcome

PARSED = normalize("convert a pdf into json")
QUERY = RecallQuery(task="convert a pdf into json")


def _outcome(matches: list[RecallCandidate], **kwargs: object) -> RecallOutcome:
    return RecallOutcome(
        matches=matches,
        parsed=PARSED,
        considered=int(kwargs.get("considered", 0)),
        cleared=int(kwargs.get("cleared", 0)),
        best_score=float(kwargs.get("best_score", 0.0)),
    )


def _candidate() -> RecallCandidate:
    return RecallCandidate(
        experience_id="exp_1",
        version=1,
        experience_version_id="ver_1",
        goal="convert pdf to json",
        relevance=0.9,
        compatibility=Compatibility.HIGH,
        confidence=0.5,
        successful_runs=3,
        recommendation=Recommendation.USE,
        evidence=Evidence(),
        requires_network=False,
    )


def test_a_zero_match_recall_queues_exactly_one_miss() -> None:
    background = BackgroundTasks()

    routes._remember_miss(
        background,
        _outcome([], considered=12, cleared=0, best_score=0.29),
        QUERY.task,
        Principal(organization_id="org_x", agent_id="agt_x"),
        QUERY,
    )

    assert len(background.tasks) == 1
    task = background.tasks[0]
    assert task.func is misses.record
    # The whole point of the row: "nearly matched" is distinguishable from
    # "nothing remotely close".
    assert task.kwargs["candidates"] == 12
    assert task.kwargs["cleared"] == 0
    assert task.kwargs["best_score"] == 0.29
    assert task.kwargs["task"] == QUERY.task
    assert task.kwargs["parsed"].canonical == "pdf_to_json"
    assert task.kwargs["environment"]["os"] == "linux"
    assert task.kwargs["constraints"]["network"] is False
    assert task.kwargs["organization_id"] == "org_x"


def test_a_matched_recall_queues_nothing() -> None:
    background = BackgroundTasks()

    routes._remember_miss(
        background,
        _outcome([_candidate()], considered=12, cleared=1, best_score=0.71),
        QUERY.task,
        Principal(organization_id="org_x", agent_id="agt_x"),
        QUERY,
    )

    assert background.tasks == []


def test_an_anonymous_recall_is_attributed_to_nobody() -> None:
    """Recall is keyless, so most misses have no organization. Not a problem --
    but the anonymous principal names an org row that does not exist, and
    storing that id would be a lie dressed as attribution."""
    background = BackgroundTasks()

    routes._remember_miss(background, _outcome([]), QUERY.task, routes.ANONYMOUS, QUERY)

    assert background.tasks[0].kwargs["organization_id"] is None


def test_one_need_asked_two_ways_is_one_fingerprint() -> None:
    """The bound on the table. Recall is public and keyless, so without this a
    script could write a row per request forever."""
    environment: dict[str, object] = {"os": "linux"}
    constraints: dict[str, object] = {"network": False}

    first = misses.fingerprint(None, normalize("convert a pdf into json"), environment, constraints)
    same = misses.fingerprint(
        None, normalize("please convert the pdf documents into json"), environment, constraints
    )
    other = misses.fingerprint(None, normalize("validate a yaml file"), environment, constraints)

    assert first == same
    assert first != other


async def test_a_failed_miss_write_does_not_raise() -> None:
    """Telemetry that can break the product it measures is worse than none."""

    def explode() -> object:
        raise RuntimeError("no database tonight")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(misses.database, "session", explode)
        await misses.record(
            task=QUERY.task,
            parsed=PARSED,
            environment={},
            constraints={},
            candidates=0,
            cleared=0,
            best_score=0.0,
            organization_id=None,
        )
