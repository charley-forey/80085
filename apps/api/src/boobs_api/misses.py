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
  and a counter; and a retention window, swept on write.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from boobs_common import ids
from boobs_common.clock import now
from boobs_observability import logger
from boobs_retrieval.intent import Intent
from boobs_schemas import db as database
from boobs_schemas.tables import RecallMiss

log = logger(__name__)

# Long enough to see a seasonal pattern in demand, short enough that
# user-supplied task text is not kept indefinitely. Stated in docs/security.md,
# where someone deciding whether to type something into recall can find it.
RETENTION = timedelta(days=90)


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


async def record(
    *,
    task: str,
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
                task=task,
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
            # ponytail: swept on write rather than by a scheduler, because this
            # stack has no scheduler and adding one to delete a handful of rows
            # would be the larger change. It is an indexed range delete that
            # matches nothing on almost every call. Move it to a cron job if
            # misses ever arrive fast enough for the delete to show up.
            await session.execute(
                delete(RecallMiss).where(RecallMiss.last_seen_at < timestamp - RETENTION)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - a lost miss must never cost a recall
        log.warning("recall_miss_not_recorded", error=str(exc), kind=type(exc).__name__)
