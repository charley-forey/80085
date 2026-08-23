"""Two races, against the database that actually arbitrates them.

The unit tests state both properties as orderings. These state them as a
caller experiences them, and add what a fake session cannot: the append-only
triggers, `uq_experience_version`, and the evidence recomputed from the rows
that survive.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from boobs_api import leases
from boobs_common.clock import now
from boobs_domain.enums import ExecutionStatus
from boobs_schemas.tables import Execution
from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap, record_experience

pytestmark = [pytest.mark.integration]

DIGEST = "sha256:" + "9a" * 32


async def _worker_key(api: httpx.AsyncClient, name: str) -> dict[str, str]:
    return auth(await bootstrap(api, f"{name}-org", name, [Scope.WORKER]))


async def _claim(db: Any, execution_id: str, worker_id: str) -> None:
    """Put the row in the state a lease would have left it in.

    Not `POST /v1/worker/lease`: the queue is one table shared by the whole
    session, so leasing here would claim -- and count an attempt against --
    whichever execution another test happens to have waiting. What is under
    test is what `report_result` does with the row, and this is the row.
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


def _result(worker_id: str, status: str, exit_code: int) -> dict[str, Any]:
    return {
        "worker_id": worker_id,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": 5,
    }


async def test_a_stale_worker_cannot_overwrite_a_finished_execution(
    api: httpx.AsyncClient, db: Any
) -> None:
    """Worker A's lease expires, B takes the job and fails it, A reports late.

    A's SUCCEEDED must not land: `evidence.recompute` reads these rows and
    trusts them, so a stale write here is a manufactured success in the corpus.
    """
    key = await bootstrap(api, "stale-org", "stale-agent")
    experience_id = await record_experience(
        api, key, "Stale lease test capability", "stale_lease", DIGEST
    )
    run = await api.post(f"/v1/experiences/{experience_id}/execute", headers=auth(key), json={})
    execution_id = run.json()["execution_id"]

    worker = await _worker_key(api, "stale-worker")

    # A holds a lease it will not report on in time; it expires, the next lease
    # reclaims the row (tests/integration/test_worker_poison_jobs.py covers
    # that half), and B claims it and finds the run broken.
    await _claim(db, execution_id, "worker-a")
    await _claim(db, execution_id, "worker-b")
    finished = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=worker,
        json=_result("worker-b", "failed", 1),
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["accepted"] is True

    # And now A's slow run finally comes back, claiming success.
    late = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=worker,
        json=_result("worker-a", "succeeded", 0),
    )
    assert late.status_code == 200, late.text
    body = late.json()
    assert body["accepted"] is False
    assert body["status"] == ExecutionStatus.FAILED

    await db.rollback()  # see the committed row, not this session's snapshot
    recorded = (
        await db.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one()
    assert recorded.status == ExecutionStatus.FAILED
    assert recorded.exit_code == 1
    assert recorded.leased_by == "worker-b"


async def test_two_recordings_of_the_same_experience_never_500(api: httpx.AsyncClient) -> None:
    """Concurrent versions either both land or one is told to try again.

    Whether the race is actually reached depends on how the two transactions
    interleave, which is not something a test can insist on. What it can insist
    on is that neither outcome is a 500 and that no two versions of one
    Experience ever share a number.
    """
    key = await bootstrap(api, "version-race-org", "version-race-agent")
    experience_id = await record_experience(
        api, key, "Version race test capability", "version_race", DIGEST
    )

    async def record() -> httpx.Response:
        return await api.post(
            "/v1/experiences",
            headers=auth(key),
            json={
                "experience_id": experience_id,
                "goal": {"statement": "Version race test capability", "intent": "version_race"},
                "artifact": {
                    "type": "oci",
                    "reference": f"registry.test/80085/version_race@{DIGEST}",
                },
                "command": ["python", "/app/main.py"],
                "environment": {"os": "linux", "architecture": "amd64", "runtime": "python"},
                "visibility": "public",
            },
        )

    responses = await asyncio.gather(record(), record())

    assert [r.status_code for r in responses] != [500, 500]
    for response in responses:
        assert response.status_code in (201, 409), response.text

    versions = [r.json()["version"] for r in responses if r.status_code == 201]
    assert len(versions) == len(set(versions)), versions


async def test_reclaim_returns_the_job_and_a_late_report_is_not_an_error(
    api: httpx.AsyncClient, db: Any
) -> None:
    """The simpler half: nobody has taken the job over yet, it is merely back
    in the queue. The worker that lost it is still not at fault."""
    key = await bootstrap(api, "requeued-org", "requeued-agent")
    experience_id = await record_experience(
        api, key, "Requeued lease test capability", "requeued_lease", DIGEST
    )
    run = await api.post(f"/v1/experiences/{experience_id}/execute", headers=auth(key), json={})
    execution_id = run.json()["execution_id"]

    worker = await _worker_key(api, "requeued-worker")
    await _claim(db, execution_id, "worker-slow")

    execution = (
        await db.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one()
    execution.lease_expires_at = now() - timedelta(minutes=1)
    await db.commit()
    assert await leases.reclaim_expired(db) >= 1
    await db.commit()

    late = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=worker,
        json=_result("worker-slow", "succeeded", 0),
    )
    assert late.status_code == 200, late.text
    assert late.json()["accepted"] is False
    assert late.json()["status"] == ExecutionStatus.QUEUED
