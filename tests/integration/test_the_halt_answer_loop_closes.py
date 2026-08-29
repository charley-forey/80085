"""A halt becomes a question, a human answers once, and nothing asks again.

This is the loop the benchmarks pointed at. An agent that cannot determine a
convention refuses to guess (DECISIONS 80) -- and until now that refusal
evaporated: somebody answered it in a chat window and the next agent halted on
the same thing. The registry stored *solutions*, which is the thesis the
benchmarks killed.

What is asserted here is the property that makes it a loop rather than a log:

    the second agent does not have to ask.

Everything else in this file exists to make that assertion mean something --
that the match is semantic rather than string equality, that it is scoped to one
tenant, and that an answer carries a name.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import bootstrap_sync

pytestmark = [pytest.mark.integration]


@pytest.fixture
def asker(api_url: str) -> dict[str, Any]:
    return bootstrap_sync(api_url, "halt-loop-asker", "agent-one")


@pytest.fixture
def stranger(api_url: str) -> dict[str, Any]:
    """A different organisation entirely. Its questions are none of ours."""
    return bootstrap_sync(api_url, "halt-loop-stranger", "agent-two")


def _auth(account: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['api_key']}"}


async def test_the_second_agent_does_not_have_to_ask(
    api: httpx.AsyncClient, asker: dict[str, Any]
) -> None:
    """The whole point, in one test."""
    head = _auth(asker)
    need = "Whether ST=H rows in the NWF remittance advice count as settled"

    first = await api.post("/v1/questions", headers=head, json={"need": need})
    assert first.status_code == 201, first.text
    question_id = first.json()["question_id"]
    # Nobody has answered it yet, so the first agent is genuinely stuck. That is
    # the correct outcome -- a stopped agent beats a confident wrong number.
    assert first.json()["answer"] is None

    answered = await api.post(
        f"/v1/questions/{question_id}/answer",
        headers=head,
        json={"body": "H rows are holds and settle in a later advice.", "answered_by": "priya"},
    )
    assert answered.status_code == 201, answered.text

    # A second agent, phrasing it its own way, does not halt.
    again = await api.post(
        "/v1/questions",
        headers=head,
        json={"need": "Do held rows count toward the settled total in this remittance file?"},
    )
    assert again.status_code == 201, again.text
    body = again.json()
    assert body["question_id"] == question_id, "a rephrasing must not open a second question"
    assert body["answer"] is not None, "the loop did not close"
    assert "settle in a later advice" in body["answer"]["body"]
    assert body["answer"]["answered_by"] == "priya"
    assert body["asked"] == 2


async def test_a_question_never_crosses_a_tenant_boundary(
    api: httpx.AsyncClient, asker: dict[str, Any], stranger: dict[str, Any]
) -> None:
    """A question is a fact about one company's decisions.

    Matching one organisation's halt against another's answer is not a useful
    hit. It is a leak, and it would be a leak of exactly the thing a client
    deployed this privately to keep.
    """
    need = "Whether our coverage end_date is inclusive or exclusive"
    ours = await api.post("/v1/questions", headers=_auth(asker), json={"need": need})
    await api.post(
        f"/v1/questions/{ours.json()['question_id']}/answer",
        headers=_auth(asker),
        json={"body": "Exclusive. Cover ceases at 00:00.", "answered_by": "priya"},
    )

    theirs = await api.post("/v1/questions", headers=_auth(stranger), json={"need": need})
    assert theirs.status_code == 201, theirs.text
    assert theirs.json()["answer"] is None, "another tenant's answer was served across the boundary"
    assert theirs.json()["question_id"] != ours.json()["question_id"]


async def test_unanswered_reports_what_agents_are_stuck_on_most(
    api: httpx.AsyncClient, asker: dict[str, Any]
) -> None:
    """The one report worth a human's attention, ordered by what it is costing."""
    head = _auth(asker)
    quiet = "Whether the freight surcharge column is already included in the line total"
    loud = "Which timezone the settlement cutoff in this export is expressed in"

    await api.post("/v1/questions", headers=head, json={"need": quiet})
    for _ in range(3):
        await api.post("/v1/questions", headers=head, json={"need": loud})

    report = await api.get("/v1/questions/unanswered", headers=head)
    assert report.status_code == 200, report.text
    rows = report.json()["questions"]
    needs = [row["need"] for row in rows]
    assert loud in needs and quiet in needs
    # Most-asked first: a question asked three times and never answered is
    # costing three times as much as one asked once.
    assert needs.index(loud) < needs.index(quiet)
    assert next(r for r in rows if r["need"] == loud)["asked"] == 3


async def test_an_answer_supersedes_rather_than_overwrites(
    api: httpx.AsyncClient, asker: dict[str, Any]
) -> None:
    """An answer that turned out wrong is the row somebody most needs to find.

    Since decision 74 an agent told to defer believes what it is handed, so a
    corrected answer must take effect immediately -- and the one it replaced must
    still exist, because that is the audit trail for whatever the wrong one
    caused.
    """
    head = _auth(asker)
    need = "Whether quantities in the stock export are units or cases"
    question_id = (await api.post("/v1/questions", headers=head, json={"need": need})).json()[
        "question_id"
    ]

    for body, who in (("Units.", "sam"), ("Cases of twelve. The earlier answer was wrong.", "dev")):
        posted = await api.post(
            f"/v1/questions/{question_id}/answer",
            headers=head,
            json={"body": body, "answered_by": who},
        )
        assert posted.status_code == 201, posted.text

    served = await api.post("/v1/questions", headers=head, json={"need": need})
    answer = served.json()["answer"]
    assert answer["body"].startswith("Cases of twelve")
    assert answer["answered_by"] == "dev"


async def test_one_persons_answer_does_not_become_company_truth_until_verified(
    db: Any,
) -> None:
    """The two tiers, which is the whole approval model.

    An answer is typed into one agent's chat by whoever was watching it work.
    That is the right capture point -- they are already there, and routing it
    through a channel first would make halting cost more than guessing.

    But one person's sentence in one session is not a fact about the company.
    Since decision 74 an agent told to defer believes what it is handed, so the
    blast radius of a wrong answer is every agent that inherits it. Until a
    second human says otherwise, it serves only the agent that asked.

    Driven against the module rather than the API because `/v1/bootstrap` mints
    an organization per call, so there is no HTTP route to a second agent inside
    one tenant -- and testing this over two organizations would have proved
    tenant isolation again while claiming to prove something else.
    """
    from boobs_api import questions

    org = "org_two_tier_test"
    mine, theirs = "agt_watching", "agt_unattended"
    need = "Whether the settlement cutoff in this export is UTC or local time"

    question, _ = await questions.record(db, organization_id=org, agent_id=mine, need=need)
    written = await questions.answer(
        db,
        question_id=question.id,
        organization_id=org,
        body="UTC, always.",
        answered_by="priya",
        asked_by_agent=mine,
    )

    # The agent whose chat it was typed into can act on it immediately.
    assert await questions.current_answer(db, question.id, agent_id=mine) is not None
    # Another agent in the same company cannot -- yet.
    assert await questions.current_answer(db, question.id, agent_id=theirs) is None
    # Nor can anything running unattended.
    assert await questions.current_answer(db, question.id) is None

    queued = await questions.awaiting_verification(db, organization_id=org)
    assert any(a.id == written.id for a, _ in queued)

    await questions.verify(db, answer_id=written.id, organization_id=org, verified_by="dev")

    # Now it is company knowledge, for agents nobody is watching.
    assert await questions.current_answer(db, question.id, agent_id=theirs) is not None
    assert await questions.current_answer(db, question.id) is not None
    after = await questions.awaiting_verification(db, organization_id=org)
    assert not any(a.id == written.id for a, _ in after)
