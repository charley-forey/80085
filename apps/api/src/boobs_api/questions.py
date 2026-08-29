"""Halts, recorded as questions, and the answers that close them.

The registry this system started as stores *solutions*: somebody decided a
capability would be useful, wrote it, and recorded it. The benchmarks measured
what that produces -- 36 of 37 entries were things agents did not need
(DECISIONS 81) -- because we were guessing at demand.

This stores *questions*, and it cannot guess. Every row begins with a real agent
on real data that could not determine a convention and refused to guess at it
(DECISIONS 80). The corpus grows only where something actually asked.

The whole loop:

    agent halts        ->  record()      the question, deduplicated
    human answers      ->  answer()      once, with a name against it
    next agent halts   ->  recall()      and gets the answer instead

Matching is semantic and tenant-scoped, in that order of importance. A question
is "which reading of an end date does *this company* use", which is a fact about
one organisation's decisions -- so a match across a tenant boundary is not a
useful hit, it is a leak.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common import ids
from boobs_common.clock import now
from boobs_retrieval.embedding import embed_in_thread, embedder
from boobs_schemas.tables import Answer, Question

# Cosine distance below which two phrasings are the same question. Deliberately
# tighter than recall's threshold for capabilities: a wrong capability wastes a
# run, and a wrong answer here is believed (DECISIONS 75).
SAME_QUESTION = 0.25


async def _vector(need: str) -> list[float]:
    return (await embed_in_thread(embedder(), [need]))[0]


async def record(
    db: AsyncSession,
    *,
    organization_id: str,
    agent_id: str | None,
    need: str,
    context: dict[str, Any] | None = None,
) -> tuple[Question, Answer | None]:
    """Record a halt, or count it against the question already asked.

    Returns the question and its answer if one exists -- so an agent that halts
    on something already answered gets the answer in the same round trip rather
    than halting and then having to ask again.
    """
    vector = await _vector(need)
    existing, answer = await nearest(
        db, organization_id=organization_id, vector=vector, agent_id=agent_id
    )
    if existing is not None:
        await db.execute(
            update(Question)
            .where(Question.id == existing.id)
            .values(asked=Question.asked + 1, last_asked_at=now())
        )
        return existing, answer

    moment = now()
    question = Question(
        id=ids.new_id(ids.QUESTION),
        organization_id=organization_id,
        agent_id=agent_id,
        need=need,
        context=context,
        embedding=vector,
        asked=1,
        created_at=moment,
        last_asked_at=moment,
    )
    db.add(question)
    await db.flush()
    return question, None


async def nearest(
    db: AsyncSession, *, organization_id: str, vector: list[float], agent_id: str | None = None
) -> tuple[Question | None, Answer | None]:
    """The same question, asked before by this organisation, and its answer."""
    row = (
        await db.execute(
            select(Question, Question.embedding.cosine_distance(vector).label("d"))
            .where(
                Question.organization_id == organization_id,
                Question.embedding.is_not(None),
            )
            .order_by("d")
            .limit(1)
        )
    ).first()
    if row is None or row.d > SAME_QUESTION:
        return None, None
    return row[0], await current_answer(db, row[0].id, agent_id=agent_id)


async def current_answer(
    db: AsyncSession, question_id: str, *, agent_id: str | None = None
) -> Answer | None:
    """The answer this caller may act on, if there is one.

    Two tiers, because where an answer is captured and where it becomes true for
    everybody are different moments. A verified answer serves the whole
    organisation. An unverified one serves only the agent whose chat it was
    typed into -- which is where it was going to be used anyway, and no further.

    Without that split, one person answering one agent's question in one session
    silently becomes a fact the whole company defers to, and decision 75
    measured what a wrong fact costs once agents are told to believe it.
    """
    rows = (
        await db.execute(
            select(Answer)
            .where(Answer.question_id == question_id, Answer.superseded_by.is_(None))
            .order_by(Answer.answered_at.desc())
        )
    ).scalars()
    for row in rows:
        if row.verified_at is not None:
            return row
        if agent_id is not None and row.asked_by_agent == agent_id:
            return row
    return None


async def answer(
    db: AsyncSession,
    *,
    question_id: str,
    organization_id: str,
    body: str,
    answered_by: str,
    asked_by_agent: str | None = None,
) -> Answer:
    """Answer a question, superseding whatever stood before it.

    Supersession rather than replacement: an answer that turned out wrong is the
    row somebody most needs to find, and overwriting it destroys the audit trail
    at exactly the moment it matters.
    """
    fresh = Answer(
        id=ids.new_id(ids.ANSWER),
        question_id=question_id,
        organization_id=organization_id,
        body=body,
        answered_by=answered_by,
        answered_at=now(),
        asked_by_agent=asked_by_agent,
    )
    db.add(fresh)
    await db.flush()
    await db.execute(
        update(Answer)
        .where(
            Answer.question_id == question_id,
            Answer.id != fresh.id,
            Answer.superseded_by.is_(None),
        )
        .values(superseded_by=fresh.id)
    )
    return fresh


async def unanswered(db: AsyncSession, *, organization_id: str, limit: int = 50) -> list[Question]:
    """What agents are stuck on, most-asked first.

    The one report worth putting in front of a human. A question asked forty
    times and never answered is the most expensive row in the database: forty
    agent runs that stopped, or worse, forty that did not.
    """
    answered = select(Answer.question_id).where(Answer.superseded_by.is_(None))
    rows = await db.execute(
        select(Question)
        .where(Question.organization_id == organization_id, Question.id.not_in(answered))
        .order_by(Question.asked.desc(), Question.last_asked_at.desc())
        .limit(limit)
    )
    return list(rows.scalars())


async def verify(
    db: AsyncSession, *, answer_id: str, organization_id: str, verified_by: str
) -> Answer | None:
    """Promote an answer from one agent's session to the whole organisation.

    The second human. Whoever typed the answer was solving their own problem;
    this is somebody saying it is true generally -- which is a different claim,
    and the only one that should reach agents nobody is watching.

    Deliberately not self-service by the same person: this system cannot tell
    two humans apart, so the separation is procedural rather than enforced, and
    saying so is more honest than implying a check that does not exist.
    """
    found = (
        await db.execute(
            select(Answer).where(
                Answer.id == answer_id,
                Answer.organization_id == organization_id,
                Answer.superseded_by.is_(None),
            )
        )
    ).scalar_one_or_none()
    if found is None:
        return None
    found.verified_at = now()
    found.verified_by = verified_by
    await db.flush()
    return found


async def awaiting_verification(
    db: AsyncSession, *, organization_id: str, limit: int = 50
) -> list[tuple[Answer, Question]]:
    """Answers one person gave that nobody else has confirmed yet.

    The approval queue, whether that is a dashboard, a channel post or somebody
    reading it once a week. Ordered by how many agents are waiting on it.
    """
    rows = await db.execute(
        select(Answer, Question)
        .join(Question, Question.id == Answer.question_id)
        .where(
            Answer.organization_id == organization_id,
            Answer.superseded_by.is_(None),
            Answer.verified_at.is_(None),
        )
        .order_by(Question.asked.desc(), Answer.answered_at.desc())
        .limit(limit)
    )
    return [(a, q) for a, q in rows]
