"""Record what agents asked for and did not find.

The cheap half of failure knowledge (spec section 23, deferred in
`DECISIONS.md`). A recall that matches nothing is the most valuable row this
system can write and the only one it can never backfill: it names a capability
somebody wanted, in their own words, on a day nobody had recorded it.

Three properties this module exists to guarantee, in order of importance:

* **It cannot fail a recall.** Every write runs after the response has been
  sent, on its own session, inside a `try` that only logs. Telemetry that can
  break the product it measures is worse than no telemetry.
* **It cannot slow a recall.** Nothing here runs inside the request.
* **It cannot grow without bound.** Recall is keyless and public, so this table
  is an abuse target. Two bounds: an upsert on a fingerprint over the
  *normalized* intent, so a thousand rephrasings of one unmet need are one row
  and a counter; and a retention window, swept by `80085-scheduler retention`
  with the write path as its fallback until that cron exists (decision 54).
* **It cannot retain what somebody typed.** The row used to carry the raw task
  text. It no longer carries any free text at all: `vocabulary()` keeps only
  labels written in `boobs_retrieval.intent`, so the worst thing a caller can
  put in this table is a word we chose. Decision 49.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common import ids
from boobs_common.clock import now
from boobs_observability import logger
from boobs_retrieval.intent import Intent
from boobs_schemas import db as database
from boobs_schemas.tables import RecallMiss

log = logger(__name__)

# Long enough to see a seasonal pattern in demand, short enough that a gap
# nobody has asked about since spring stops being counted as demand. It was
# also the bound on how long user-supplied text was kept; there is no longer
# any, which makes this a data-quality window rather than a privacy one.
RETENTION = timedelta(days=90)

# Set to "0" on the API once `80085-scheduler retention` is confirmed running.
# It defaults to on so that deploying this code cannot be the moment retention
# quietly stopped -- see `sweep` and decision 54.
SWEEP_ON_WRITE = "BOOBS_MISS_SWEEP_ON_WRITE"


async def sweep(session: AsyncSession) -> int:
    """Delete misses nobody has asked for since `RETENTION` ago.

    The one implementation of retention, called from two places: the scheduled
    job in `boobs_api.scheduler`, and the fallback below. It does not commit --
    the write path folds it into the transaction that wrote the miss.
    """
    # `AsyncSession.execute` is typed as the read-shaped `Result`; a DELETE
    # always yields a `CursorResult`, which is the half that counts rows.
    result = cast(
        CursorResult[Any],
        await session.execute(
            delete(RecallMiss).where(RecallMiss.last_seen_at < now() - RETENTION)
        ),
    )
    return int(result.rowcount or 0)


def fingerprint(
    organization_id: str | None,
    parsed: Intent,
    environment: dict[str, Any],
    constraints: dict[str, Any],
) -> str:
    """The identity of an unmet need, not of a request.

    Deliberately over the *normalized* intent rather than the raw text: "turn a
    pdf into json" and "convert PDF documents to JSON please" are one demand
    signal, and storing them as two would both overstate the corpus's gaps and
    hand a flooder a free row per keystroke.
    """
    material = json.dumps(
        [organization_id, parsed.canonical, parsed.normalized, environment, constraints],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def vocabulary(parsed: Intent) -> str:
    """The words of a task we are willing to keep: the ones we wrote ourselves.

    Every value this can return is a key of `FORMATS` or `ACTIONS` in
    `boobs_retrieval.intent` -- a closed list in our own source. A task that
    names a customer, a hostname or a patient yields at most `convert pdf`.

    It exists because `intent` alone loses the gaps most worth knowing about.
    `Intent.canonical` collapses to `"unknown"` whenever no action matched,
    including when a format did, so "something weird involving our PDFs" and
    "no idea what this person wanted" would otherwise be the same row to read.
    `terms` keeps them apart at the cost of nothing user-supplied.

    Deliberately *not* `Intent.keywords` or `Intent.normalized`, which are the
    raw text minus stopwords -- a customer name survives both intact.
    """
    return " ".join(
        sorted({t for t in (parsed.action, parsed.source_format, parsed.target_format) if t})
    )


async def record(
    *,
    parsed: Intent,
    environment: dict[str, Any],
    constraints: dict[str, Any],
    candidates: int,
    cleared: int,
    best_score: float,
    organization_id: str | None,
) -> None:
    """Write one miss. Never raises -- this is telemetry, not the product."""
    timestamp = now()
    try:
        async with database.session() as session:
            statement = insert(RecallMiss).values(
                id=ids.new_id(ids.RECALL_MISS),
                fingerprint=fingerprint(organization_id, parsed, environment, constraints),
                organization_id=organization_id,
                terms=vocabulary(parsed),
                intent=parsed.canonical,
                environment=environment,
                constraints=constraints,
                candidates=candidates,
                cleared=cleared,
                best_score=best_score,
                occurrences=1,
                first_seen_at=timestamp,
                last_seen_at=timestamp,
            )
            # The same need asked again is a stronger signal, not a second one.
            # `best_score` takes the maximum so a row records the closest the
            # corpus ever came, not merely how close it came most recently.
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[RecallMiss.fingerprint],
                    set_={
                        "occurrences": RecallMiss.occurrences + 1,
                        "last_seen_at": timestamp,
                        "candidates": statement.excluded.candidates,
                        "cleared": statement.excluded.cleared,
                        "best_score": func.greatest(
                            RecallMiss.best_score, statement.excluded.best_score
                        ),
                    },
                )
            )
            # ponytail: retention has a proper home now -- `80085-scheduler
            # retention` -- and this is the fallback for a deployment where
            # nobody has created the cron service yet. It stays on by default
            # because the alternative is that shipping this code is the moment
            # retention silently stopped. Ceiling: an indexed range delete
            # inside the miss write, which is what it always was. Set
            # BOOBS_MISS_SWEEP_ON_WRITE=0 once the cron is confirmed running.
            if os.environ.get(SWEEP_ON_WRITE, "1").strip() != "0":
                removed = await sweep(session)
                if removed:
                    # Deliberately a warning, and deliberately only when it
                    # deletes something. With the job running there is never
                    # anything left here to delete, so this line appearing at
                    # all is the symptom of a cron nobody made -- or made and
                    # broke. It is the only alarm a forgotten schedule sets off.
                    log.warning(
                        "recall_miss_retention_swept_on_write",
                        removed=removed,
                        job="80085-scheduler retention",
                    )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - a lost miss must never cost a recall
        log.warning("recall_miss_not_recorded", error=str(exc), kind=type(exc).__name__)
