"""Readiness must fail when recall would fail.

A Postgres image without pgvector answers `SELECT 1` happily while every
recall returns 500. That happened in production and `/v1/ready` reported the
database as healthy throughout, so the check now exercises the vector type
itself.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.integration]


async def test_ready_reports_pgvector_separately(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert body["checks"]["pgvector"] is True, (
        "pgvector is unusable; recall will 500 even though the database answers"
    )
    assert "queued_executions" in body


async def test_ready_is_unauthenticated(api: httpx.AsyncClient) -> None:
    """Probes must not need a credential."""
    assert (await api.get("/v1/health")).status_code == 200
    assert (await api.get("/v1/ready")).status_code == 200


async def test_ready_distinguishes_a_busy_worker_from_no_worker(api: httpx.AsyncClient) -> None:
    """A queue depth alone cannot tell an outage from a backlog.

    Twelve queued with a fresh lease is a worker keeping up badly; twelve
    queued with a stale one is no worker attached. To an agent whose execution
    sits at `queued` those look identical, and the second is the one that reads
    from outside as "this product does not work".
    """
    body = (await api.get("/v1/ready")).json()
    workers = body["workers"]
    # Both keys always present: a field that vanishes when nothing has ever run
    # is indistinguishable from a field nobody thought to look for.
    assert set(workers) == {"last_lease_at", "last_lease_age_seconds"}
    if workers["last_lease_at"] is None:
        assert workers["last_lease_age_seconds"] is None
    else:
        assert workers["last_lease_age_seconds"] >= 0
