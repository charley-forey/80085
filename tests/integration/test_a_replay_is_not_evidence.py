"""A replayed run is not a verification of anything.

Decision 20 asked for this test by name before the worker cache could be
reported at all: `recompute` treats one terminal `executions` row as one
independent verification run, and it learns about that run from what a worker
says. A worker that served a cache hit and reported it like any other run would
have the platform record a verification of something that never executed.

So the property, stated the way a caller experiences it: a replay moves no
number on the evidence -- not the counts, not the confidence, not the duration
percentiles -- and a genuine run moves all of them. Against the real API, the
real verifier, the real triggers and the real recompute, because the failure
this guards against is the numbers being wrong rather than a function being
called with the wrong argument.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from boobs_api import leases
from boobs_common.clock import now
from boobs_domain.enums import ExecutionStatus
from boobs_schemas.tables import Execution, Verification
from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap, record_experience

pytestmark = [pytest.mark.integration]

DIGEST = "sha256:" + "c1" * 32
# Executions are rate limited per caller address, and the whole integration
# session shares one. Its own address, so this test's three runs are its own
# budget and nobody else's exhausted one can fail it.
CALLER = {"x-forwarded-for": "192.0.2.51"}
# Absurd on purpose: the duration on a replay describes a run that happened on
# another machine on another day, so if it is counted it will be visible in
# p95 rather than hidden in the noise.
REPLAYED_MS = 9_000_000


async def _claim(db: Any, execution_id: str, worker_id: str) -> None:
    """Put the row in the state a lease would have left it in.

    Not `POST /v1/worker/lease`, for the reason
    `tests/integration/test_races_do_not_corrupt_evidence.py` gives: the queue
    is one table shared by the whole session, so leasing here claims whichever
    execution another test happens to have waiting.
    """
    execution = (
        await db.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one()
    execution.status = ExecutionStatus.RUNNING
    execution.leased_by = worker_id
    execution.started_at = now()
    execution.attempts += 1
    execution.lease_expires_at = now() + timedelta(seconds=leases.DEFAULT_LEASE_SECONDS)
    await db.commit()


async def _execute(api: httpx.AsyncClient, key: str, experience_id: str) -> str:
    run = await api.post(
        f"/v1/experiences/{experience_id}/execute",
        headers={**auth(key), **CALLER},
        json={},
    )
    assert run.status_code == 202, run.text
    return str(run.json()["execution_id"])


async def _report(
    api: httpx.AsyncClient,
    worker: dict[str, str],
    execution_id: str,
    worker_id: str,
    duration_ms: int,
    *,
    cached: bool = False,
) -> dict[str, Any]:
    response = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=worker,
        json={
            "worker_id": worker_id,
            "status": "succeeded",
            "exit_code": 0,
            "duration_ms": duration_ms,
            "cached": cached,
        },
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["accepted"] is True, body
    return body


async def _evidence(api: httpx.AsyncClient, key: str, experience_id: str) -> dict[str, Any]:
    response = await api.get(f"/v1/experiences/{experience_id}", headers=auth(key))
    assert response.status_code == 200, response.text
    return dict(response.json()["evidence"])


async def test_a_replay_moves_no_evidence_and_a_real_run_still_does(
    api: httpx.AsyncClient, db: Any
) -> None:
    owner = await bootstrap(api, "replay-owner-org", "replay-owner")
    worker = auth(await bootstrap(api, "replay-worker-org", "replay-worker", [Scope.WORKER]))

    # Private, and not incidentally. The corpus is shared with every other
    # test in this session, and this row is about to become the best-evidenced
    # one in it: two verified runs where every other fixture has none.
    # Recorded public it outranked everything for anything, and answered the
    # deliberately unmatchable tasks in test_recall_misses_report -- which
    # asserts they find nothing, because a recall that matches records no
    # miss. Anything here that ends up well-evidenced wants the same
    # treatment.
    experience_id = await record_experience(
        api,
        owner,
        "Deterministic capability that gets run twice",
        "replayed_evidence",
        DIGEST,
        verification={"verifier": "exit_code", "config": {}},
        visibility="private",
    )

    # One genuine run, which is evidence: it happened, and the API verified it.
    first = await _execute(api, owner, experience_id)
    await _claim(db, first, "worker-honest")
    assert (await _report(api, worker, first, "worker-honest", 40))["verified"] is True

    baseline = await _evidence(api, owner, experience_id)
    assert baseline["successful_runs"] == 1
    assert baseline["failed_runs"] == 0
    assert baseline["confidence"] > 0
    assert baseline["median_duration_ms"] == 40
    assert baseline["p95_duration_ms"] == 40

    # Now the same artifact with the same inputs is asked for again and the
    # worker replays the first run's bytes. This is the whole point: it is
    # served, it is recorded, and it proves nothing.
    replayed = await _execute(api, owner, experience_id)
    await _claim(db, replayed, "worker-cache")
    body = await _report(api, worker, replayed, "worker-cache", REPLAYED_MS, cached=True)

    # Not verified, because there is nothing to verify. `verifications` is
    # append-only and feeds the strongest level and last_verified_at, so a
    # verdict about a run that did not happen could never be taken back.
    assert body["verified"] is None
    assert body["verifier"] is None

    # Every number, not a chosen few: the counts, the success rate, the
    # confidence, both percentiles, the organizations and the failure modes.
    assert await _evidence(api, owner, experience_id) == baseline

    # The row is kept, and says what it was. A caller asked and got an answer;
    # that is a fact worth storing and worth billing for. It is simply not a
    # verification, and it carries no verdict.
    await db.rollback()  # see the committed rows, not this session's snapshot
    row = (await db.execute(select(Execution).where(Execution.id == replayed))).scalar_one()
    assert row.cached is True
    assert row.status == ExecutionStatus.SUCCEEDED
    assert row.completed_at is not None
    verdicts = (
        (await db.execute(select(Verification.id).where(Verification.execution_id == replayed)))
        .scalars()
        .all()
    )
    assert verdicts == []

    # And the numbers did not stop moving -- they stopped counting a replay. A
    # run that actually happens still lands, with its own duration.
    genuine = await _execute(api, owner, experience_id)
    await _claim(db, genuine, "worker-honest-2")
    assert (await _report(api, worker, genuine, "worker-honest-2", 60))["verified"] is True

    after = await _evidence(api, owner, experience_id)
    assert after["successful_runs"] == 2
    assert after["failed_runs"] == 0
    assert after["confidence"] > baseline["confidence"]
    assert after["p95_duration_ms"] == 60
