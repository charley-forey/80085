"""A degraded embedder has to be visible from outside the process.

`embedder()` is lru_cached and `BOOBS_EMBEDDER=auto` falls back to the
non-semantic HashingEmbedder when the model will not load, so a single startup
failure quietly degrades every recall for the life of the process. The evidence
used to be one log line. It is now a field on /v1/ready.

Readiness deliberately stays *true* on the fallback -- see DECISIONS.md 22.
Reporting unready would have the platform cycle a container that cannot fetch a
model, turning a degradation into an outage, while lexical recall still answers
and MIN_SCORE still refuses a weak match.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Response

from boobs_api import routes
from boobs_common import storage
from boobs_retrieval import embedding


class _Result:
    def scalars(self) -> list[Any]:
        return []


class _Session:
    """A database that answers, which is all readiness asks of it here."""

    async def execute(self, *_: Any, **__: Any) -> _Result:
        return _Result()

    async def rollback(self) -> None:
        return None


@pytest.fixture
def hashing(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("BOOBS_EMBEDDER", "hashing")
    embedding.embedder.cache_clear()
    # Object storage is the one check here that would reach the network.
    monkeypatch.setattr(storage, "healthy", _healthy)
    yield
    embedding.embedder.cache_clear()


async def _healthy() -> bool:
    return True


async def test_ready_reports_the_active_embedder(hashing: None) -> None:
    body = await routes.ready(_Session(), Response())  # type: ignore[arg-type]

    assert body["checks"]["embedder"] == "hashing"


async def test_the_hashing_fallback_does_not_make_the_api_unready(hashing: None) -> None:
    """Visible, not fatal. Recall degrades; the API still answers correctly."""
    response = Response()

    body = await routes.ready(_Session(), response)  # type: ignore[arg-type]

    assert body["ready"] is True
    assert response.status_code == 200
