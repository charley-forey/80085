"""Per-IP rate limits.

Recall and key minting are open to anyone, which is what makes the product
discoverable -- and what makes limits load-bearing rather than decorative.
They are the cheapest of the five defences described in AGENTS.md; the one
that actually protects the shared brain is evidence gating, because an
Experience with no verified runs is never recommended no matter who recorded
it.

ponytail: counters live in this process, so with N replicas the effective
limit is N x the number below. Railway runs one, and the numbers are set well
under what the database can take, so that is a real ceiling rather than a
silent one. Move the window into Postgres (a small table plus a periodic
delete) when a second replica appears -- Redis was deliberately removed from
this stack when the queue moved to leases, and rate limiting alone does not
justify bringing it back.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from boobs_common.errors import EightyKError


class RateLimited(EightyKError):
    """Raised when a caller exceeds a window. Rendered as HTTP 429."""


class Window:
    """A sliding window of hit timestamps, per key."""

    def __init__(self, limit: int, seconds: int, what: str) -> None:
        self.limit = limit
        self.seconds = seconds
        self.what = what
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self.seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            raise RateLimited(
                f"{self.what}: {self.limit} per "
                f"{'minute' if self.seconds == 60 else f'{self.seconds}s'} per IP. "
                "Slow down, or run your own instance -- the whole thing is open source."
            )
        hits.append(now)
        # Unbounded growth would be a memory leak dressed as a counter.
        if len(self._hits) > 50_000:
            self._prune(cutoff)

    def _prune(self, cutoff: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            del self._hits[key]


# Reading is free and should feel free. Writing costs attribution, and running
# costs real compute, so those are tighter.
RECALL = Window(60, 60, "recall")
MINT = Window(5, 3600, "minting keys")
RECORD = Window(30, 3600, "recording experiences")
EXECUTE = Window(10, 3600, "executions")


def client_ip(request: Request) -> str:
    """The caller's address as the proxy in front of us reports it."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
