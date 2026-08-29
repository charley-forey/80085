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

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
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
        if answer is not None:
            # The blast radius, counted where it is actually acted on. "What did
            # we get wrong because of this" is the first question anybody asks
            # about an answer that turned out wrong, and it needs a number.
            await db.execute(
                update(Answer).where(Answer.id == answer.id).values(served=Answer.served + 1)
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
        # A disputed answer stops being served the moment somebody says it caused
        # damage, before anybody has worked out what is true instead. Waiting for
        # a correction means serving a known-bad answer to every agent that asks
        # in the meantime.
        if row.disputed_at is not None:
            continue
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


async def assume(
    db: AsyncSession, *, question_id: str, organization_id: str, assumption: str
) -> Question | None:
    """Record that an agent proceeded on a guess because nobody had answered.

    The escape hatch, and the reason it exists is worth stating plainly: a
    blocked agent is the most likely reason somebody switches the halt off, and
    switching it off restores exactly the silent wrong answers this was built to
    stop. Refusing an escape hatch does not prevent the guess. It only prevents
    us knowing about it.

    So the guess is allowed and recorded. Every number downstream is traceable
    to it, and the question stays in the queue -- an assumption is not an answer
    and retires nothing.
    """
    found = (
        await db.execute(
            select(Question).where(
                Question.id == question_id, Question.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if found is None:
        return None
    found.assumed = assumption
    found.assumed_at = now()
    await db.flush()
    return found


async def dispute(
    db: AsyncSession, *, answer_id: str, organization_id: str, disputed_by: str, reason: str
) -> Answer | None:
    """Somebody says this answer produced a wrong result.

    Distinct from supersession on purpose. Superseding asserts what is true
    instead, and whoever noticed the damage is usually not whoever knows the
    right answer -- so requiring a correction in order to stop the bleeding
    means serving a known-bad answer to everyone who asks in the meantime.

    A disputed answer stops being served immediately and stays in the table with
    its `served` count, because that count is the blast radius somebody is about
    to need.
    """
    found = (
        await db.execute(
            select(Answer).where(Answer.id == answer_id, Answer.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if found is None:
        return None
    found.disputed_at = now()
    found.disputed_by = disputed_by
    found.disputed_reason = reason
    await db.flush()
    return found


async def stale(
    db: AsyncSession, *, organization_id: str, older_than_hours: int = 24, limit: int = 50
) -> list[Question]:
    """Questions nobody has answered, most-asked and oldest first.

    The escalation surface. A question asked forty times over three days is not
    a backlog item, it is an outage nobody has noticed: either forty agent runs
    stopped, or somebody turned the halt off and forty wrong numbers went out.
    """
    cutoff = now() - timedelta(hours=older_than_hours)
    answered = select(Answer.question_id).where(
        Answer.superseded_by.is_(None), Answer.disputed_at.is_(None)
    )
    rows = await db.execute(
        select(Question)
        .where(
            Question.organization_id == organization_id,
            Question.id.not_in(answered),
            Question.created_at < cutoff,
        )
        .order_by(Question.asked.desc(), Question.created_at)
        .limit(limit)
    )
    return list(rows.scalars())


async def convergence(db: AsyncSession, *, organization_id: str) -> dict[str, Any]:
    """Is this paying back, or is every question a new one?

    The thesis is that questions get answered once and stop recurring. If an
    organisation has a long tail of near-unique conventions then `asked` never
    climbs, every halt is a fresh interruption, and the loop costs more than it
    returns. That is a real possible outcome, and this is the instrument that
    shows it rather than a number anybody has to take on faith.

    `repeat_rate` is the share of halts that hit a question already asked. Near
    zero means no convergence. High repeat with a low `answered_share` is the
    worst quadrant: agents stopping over and over on the same unanswered thing.
    """
    totals = (
        await db.execute(
            select(
                func.count(Question.id),
                func.coalesce(func.sum(Question.asked), 0),
                func.count(Question.assumed_at),
            ).where(Question.organization_id == organization_id)
        )
    ).one()
    distinct, halts, assumed = int(totals[0]), int(totals[1]), int(totals[2])

    answered = int(
        (
            await db.execute(
                select(func.count(func.distinct(Answer.question_id))).where(
                    Answer.organization_id == organization_id,
                    Answer.superseded_by.is_(None),
                    Answer.disputed_at.is_(None),
                )
            )
        ).scalar_one()
    )
    reused = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Answer.served), 0)).where(
                    Answer.organization_id == organization_id
                )
            )
        ).scalar_one()
    )
    return {
        "distinct_questions": distinct,
        "total_halts": halts,
        "repeat_rate": round((halts - distinct) / halts, 3) if halts else 0.0,
        "answered_share": round(answered / distinct, 3) if distinct else 0.0,
        "answers_reused": reused,
        "proceeded_on_an_assumption": assumed,
        "reading": (
            "repeat_rate near zero means every halt is a new question and the loop "
            "is not paying back. High repeat with low answered_share is the worst "
            "case: agents stopping repeatedly on something nobody answered."
        ),
    }
