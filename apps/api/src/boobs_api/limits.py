"""Per-IP rate limits, counted in Postgres.

Recall and key minting are open to anyone, which is what makes the product
discoverable -- and what makes limits load-bearing rather than decorative.
They are the cheapest of the five defences described in AGENTS.md; the one
that actually protects the shared brain is evidence gating, because an
Experience with no verified runs is never recommended no matter who recorded
it.

The counters used to live in a process-local dict, so the effective limit was
N x the number below with N replicas, and reset on every deploy. One replica
made that exact rather than merely lucky, and nothing stopped a second one.
The window is now a row in `rate_limits`, which is the upgrade path
`docs/scaling.md` names: Redis was deliberately removed when the queue moved
to leases, and rate limiting alone does not justify bringing it back.

Cost per limited request: one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`
on the request's own session -- a single round trip, a single-row primary key
lookup, and no second pooled connection. Every thousandth check also deletes
expired rows.

The window is weighted, not fixed: a hit also reads the previous window's
count and discounts it by how far into the current window we are, so a
caller sitting on a boundary cannot get more than the configured limit
across the two adjacent windows the way a bare fixed window would let them.
That costs one extra read per hit, on the same row shape already in place --
no new column, no second table.

ponytail: the sweep is a full scan of a table that is small by construction --
one row per caller per window per hour. Add an index on `window_start` if it
ever stops being small, which behind a proxy that appends the real address
means a genuine flood of distinct client addresses rather than one caller
inventing them.
"""

from __future__ import annotations

import time
from typing import Final

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common.errors import EightyKError


class RateLimited(EightyKError):
    """Raised when a caller exceeds a window. Rendered as HTTP 429."""


# One statement: the row is created or incremented and the new count comes
# back, so two replicas cannot read-then-write over each other's count.
_COUNT: Final = text(
    """
    INSERT INTO rate_limits (bucket, window_start, hits)
    VALUES (:bucket, :window_start, 1)
    ON CONFLICT (bucket, window_start) DO UPDATE SET hits = rate_limits.hits + 1
    RETURNING hits
    """
)
_PREVIOUS: Final = text(
    "SELECT hits FROM rate_limits WHERE bucket = :bucket AND window_start = :window_start"
)
_SWEEP: Final = text("DELETE FROM rate_limits WHERE window_start < :cutoff")
# A counter is worth nothing after a crash: the process that comes back has
# lost the traffic that produced it anyway, and the implementation this
# replaces threw every counter away on each deploy. Waiting for the WAL to
# reach disk was the single most expensive part of a check -- measured at
# roughly half of it -- so this transaction does not wait. SET LOCAL, so it
# ends with the statement's own transaction and nothing the handler writes
# afterwards inherits it.
_DONT_WAIT_FOR_DISK: Final = text("SET LOCAL synchronous_commit = off")

# The longest window any limit below uses. A row older than this can never be
# counted again, whichever window wrote it.
_LONGEST_WINDOW: Final = 3600
_SWEEP_EVERY: Final = 1000
_since_sweep = 0


class Window:
    """A weighted window of hits, per key, counted in the database."""

    def __init__(self, limit: int, seconds: int, what: str) -> None:
        self.limit = limit
        self.seconds = seconds
        self.what = what

    def bucket(self, key: str, now: float | None = None) -> tuple[str, int]:
        """The row this hit belongs to: (counter name plus key, window start).

        The window's name is part of the row key, so two limits of different
        lengths never share a row and one cutoff can expire all of them.
        """
        now = time.time() if now is None else now
        return f"{self.what}:{key}", int(now) // self.seconds * self.seconds

    def refuse(self) -> RateLimited:
        unit = "minute" if self.seconds == 60 else f"{self.seconds}s"
        return RateLimited(
            f"{self.what}: {self.limit} per {unit} per IP. "
            "Slow down, or run your own instance -- the whole thing is open source."
        )

    async def check(self, db: AsyncSession, key: str, now: float | None = None) -> None:
        """Count this hit, and refuse if the weighted window is already full.

        Committed immediately, and before the refusal is raised, for two
        reasons. A hit is a fact about what the caller did, not about whether
        the request went on to succeed -- and get_db rolls back on exactly the
        exception this raises, so counting inside the request's transaction
        would let anyone spend a window for free by making requests that
        error. The other reason is the one that would hurt: an uncommitted
        upsert holds a row lock, and every concurrent request from the same
        address conflicts on that one row. They would queue behind each other
        for the length of a whole handler, and the limiter would become the
        bottleneck it exists to prevent.

        The previous window's count is read, not upserted, so it never takes
        a lock and never creates a row -- a window nobody hit stays absent
        from the table, which is what keeps it small by construction.

        `now` is only ever passed by tests; production always measures the
        real clock.
        """
        now = time.time() if now is None else now
        bucket, window_start = self.bucket(key, now)
        await db.execute(_DONT_WAIT_FOR_DISK)
        hits: int = (
            await db.execute(_COUNT, {"bucket": bucket, "window_start": window_start})
        ).scalar_one()
        previous: int = (
            await db.execute(
                _PREVIOUS, {"bucket": bucket, "window_start": window_start - self.seconds}
            )
        ).scalar_one_or_none() or 0
        await db.commit()
        await _sweep(db)
        weight = max(0.0, 1 - (now - window_start) / self.seconds)
        if hits + previous * weight > self.limit:
            raise self.refuse()


async def _sweep(db: AsyncSession) -> None:
    """Delete expired windows, occasionally rather than on every request."""
    global _since_sweep
    _since_sweep += 1
    if _since_sweep < _SWEEP_EVERY:
        return
    _since_sweep = 0
    await db.execute(_SWEEP, {"cutoff": int(time.time()) - _LONGEST_WINDOW})
    await db.commit()


# Reading is free and should feel free. Writing costs attribution, and running
# costs real compute, so those are tighter.
RECALL = Window(60, 60, "recall")
MINT = Window(5, 3600, "minting keys")
RECORD = Window(30, 3600, "recording experiences")
EXECUTE = Window(10, 3600, "executions")
# Verification is re-runnable by design -- the same execution may be verified
# again by a different verifier -- and each one recomputes a version's
# evidence. Dearer than a read, cheaper than a run.
VERIFY = Window(30, 3600, "verifications")
# The admin demand report. Cheap to serve and held behind ADMIN already, so
# this is not protecting the database -- it is bounding how fast a leaked admin
# key can page through every gap in the corpus.
MISSES = Window(60, 3600, "reading recall misses")
# The one admin write. Same reasoning as MISSES and a tighter number: granting
# a tier is not a thing anybody does twenty times an hour, and `extended` is an
# hour of compute per execution -- so this bounds how much a leaked admin key
# can hand out before somebody notices.
GRANT = Window(20, 3600, "granting execution tiers")
# Withdrawing an Experience from recall, or putting it back. Same reasoning and
# the same number as GRANT: nobody quarantines twenty capabilities an hour by
# hand, and this is the one admin write that can take a working capability away
# from every agent asking for it.
QUARANTINE = Window(20, 3600, "quarantining experiences")


def client_ip(request: Request) -> str:
    """The caller's address, as the proxy in front of us reports it.

    The **last** entry in X-Forwarded-For, not the first. Each hop appends the
    address it received the connection from, so everything to the left of the
    final entry is whatever the client sent -- and reading the leftmost value
    let any caller choose their own rate-limit bucket with one header. That
    matters most for minting, which is the root of the Sybil tree: a fresh
    organization per key, no identity behind it, and a spoofable limiter means
    unlimited keys.

    ponytail: this assumes exactly one trusted hop, which is what Railway is
    today. Put a CDN in front and the last entry becomes the CDN's edge
    address, collapsing every caller into a handful of buckets -- at that
    point take the Nth from the right, N being the number of proxies actually
    run. A direct connection falls back to the socket address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.strip():
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"
