"""The window is one counter, wherever the request lands.

Counters used to live in a process-local dict, so with N replicas the
effective limit was N times the configured one and every deploy handed
everybody a fresh budget. Railway runs one replica, which made the numbers
exact by accident rather than by design -- nothing stopped a second.

The interesting assertion is the one a mock cannot make: two independent
sessions, standing in for two replicas, share a count.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from boobs_api.limits import RateLimited, Window

pytestmark = [pytest.mark.integration]


async def test_two_replicas_share_one_window(db: Any) -> None:
    """`db` and the second session below are separate connections with
    separate transactions, which is all a second replica is from Postgres's
    point of view."""
    from boobs_schemas import db as database

    window = Window(limit=3, seconds=60, what=f"test-{uuid.uuid4().hex}")
    caller = "192.0.2.1"

    async with database.session() as other_replica:
        await window.check(db, caller)
        await window.check(other_replica, caller)
        await window.check(db, caller)
        with pytest.raises(RateLimited):
            await window.check(other_replica, caller)


async def test_callers_are_counted_separately(db: Any) -> None:
    window = Window(limit=1, seconds=60, what=f"test-{uuid.uuid4().hex}")
    await window.check(db, "192.0.2.2")
    await window.check(db, "192.0.2.3")
    with pytest.raises(RateLimited):
        await window.check(db, "192.0.2.2")


async def test_minting_is_capped_per_address(api: httpx.AsyncClient) -> None:
    """Minting is the root of the Sybil tree -- a fresh organization per key,
    no identity behind it -- so its limit is the one that has to hold."""
    caller = {"x-forwarded-for": "192.0.2.10"}
    for _ in range(5):
        assert (await api.post("/v1/keys", headers=caller)).status_code == 201

    refused = await api.post("/v1/keys", headers=caller)
    assert refused.status_code == 429, refused.text
    assert "open source" in refused.json()["detail"]

    # Somebody else's budget is untouched.
    other = await api.post("/v1/keys", headers={"x-forwarded-for": "192.0.2.11"})
    assert other.status_code == 201, other.text


async def test_a_caller_cannot_spend_someone_elses_budget(api: httpx.AsyncClient) -> None:
    """X-Forwarded-For is appended to by each hop, so only the last entry was
    written by the proxy. Trusting the first let a caller mint without limit by
    varying a header -- and let them exhaust an innocent address's budget."""
    spoofed = {"x-forwarded-for": "192.0.2.20, 192.0.2.21"}
    for _ in range(5):
        assert (await api.post("/v1/keys", headers=spoofed)).status_code == 201
    assert (await api.post("/v1/keys", headers=spoofed)).status_code == 429

    # The address the caller *claimed* to be paid nothing.
    honest = await api.post("/v1/keys", headers={"x-forwarded-for": "192.0.2.20"})
    assert honest.status_code == 201, honest.text
