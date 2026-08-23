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
