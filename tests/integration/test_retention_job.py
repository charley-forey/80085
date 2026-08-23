"""Retention is a claim about a `WHERE` clause, so it is tested against Postgres.

The delete this job runs used to run inside every miss write. Moving it is only
safe if it removes exactly what the write path removed -- expired rows -- and
nothing else. A mock would assert that we called `delete()`, which was never
the part in doubt.

The write-path fallback is checked here too, in both positions: it still sweeps
by default, and `BOOBS_MISS_SWEEP_ON_WRITE=0` is what turns it off. Those are
the two states an operator can put a deployment in, and getting the default
backwards is silent data retention nobody asked for.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from boobs_api import misses, scheduler
from boobs_common.clock import now
from boobs_retrieval.intent import Intent, normalize
from boobs_schemas import db as database
from boobs_schemas.tables import RecallMiss

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]


def _parsed() -> Intent:
    return normalize("convert a pdf into json")


def _miss(marker: str, age: timedelta) -> RecallMiss:
    """A miss last asked for `age` ago, holding nothing anybody typed."""
    seen = now() - age
    return RecallMiss(
        id=f"rms_retention_{marker}",
        fingerprint=f"retention-job-{marker}",
        organization_id=None,
        terms="convert pdf",
        intent="convert",
        environment={},
        constraints={},
        candidates=3,
        cleared=0,
        best_score=0.21,
        occurrences=1,
        first_seen_at=seen,
        last_seen_at=seen,
    )


async def _ids(*wanted: str) -> set[str]:
    async with database.session() as session:
        rows = await session.execute(select(RecallMiss.id).where(RecallMiss.id.in_(wanted)))
        return set(rows.scalars())


async def test_the_retention_job_deletes_expired_misses_and_spares_live_ones(db: Any) -> None:
    expired = _miss("expired", misses.RETENTION + timedelta(days=1))
    # One day inside the window on purpose: an off-by-one in the comparison
    # deletes the whole table, and a table with nothing in it still passes a
    # test that only looks at the expired row.
    live = _miss("live", misses.RETENTION - timedelta(days=1))
    db.add_all([expired, live])
    await db.commit()
    # `run` disposes the engine, as a cron process must. Let go of this
    # session first rather than leaving the fixture holding a dead pool.
    await db.close()

    removed = await scheduler.run("retention")

    assert removed >= 1
    assert await _ids(expired.id, live.id) == {live.id}


async def test_the_write_path_still_sweeps_until_the_cron_is_turned_off(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback is the whole safety argument: deploying this code must not
    be the moment retention stopped happening."""
    monkeypatch.delenv(misses.SWEEP_ON_WRITE, raising=False)
    expired = _miss("fallback_on", misses.RETENTION + timedelta(days=2))
    db.add(expired)
    await db.commit()

    await misses.record(
        parsed=_parsed(),
        environment={},
        constraints={},
        candidates=0,
        cleared=0,
        best_score=0.0,
        organization_id="org_retention_fallback",
    )

    assert await _ids(expired.id) == set()


async def test_the_write_path_sweep_can_be_turned_off(
    db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the flag is what an operator sets once the cron is confirmed."""
    monkeypatch.setitem(os.environ, misses.SWEEP_ON_WRITE, "0")
    expired = _miss("fallback_off", misses.RETENTION + timedelta(days=3))
    db.add(expired)
    await db.commit()

    await misses.record(
        parsed=_parsed(),
        environment={},
        constraints={},
        candidates=0,
        cleared=0,
        best_score=0.0,
        organization_id="org_retention_flag",
    )

    assert await _ids(expired.id) == {expired.id}
