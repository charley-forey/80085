"""Jobs that run on a clock, and nothing that decides when.

    uv run 80085-scheduler retention

**Railway is the scheduler.** A Railway service with a cron schedule runs its
start command on that schedule and expects the process to exit; this module is
the thing it starts. There is deliberately no timing logic here -- no interval,
no crontab parser, no in-process loop -- because a second opinion about when a
job should run is a second thing that can be wrong, and the platform already
holds the first. `infrastructure/railway/scheduler.md` is how the service gets
made.

**One process per run, and it exits.** Railway skips a tick whose predecessor
is still `Active`, so a job that never returns silently stops the schedule
rather than stacking up. Hence `database.dispose()` in `run` and an explicit
exit code: a job that leaves a pool open is a job that ran once.

**Exit codes are the alarm.** 0 ran, 1 raised, 2 was asked for a job that does
not exist. Railway marks a non-zero exit as a crashed deployment, which is the
only signal a cron service emits that anybody sees without going looking.

**Why this lives in `boobs_api` rather than `apps/scheduler`.** The jobs
maintain the API's own tables and need exactly the API's dependencies and
exactly the API's credentials, and they deploy from the API's image with a
different start command -- the same way `alembic upgrade head` already does. A
separate workspace member would have to depend on `80085-api` to reach the
retention window and the table it applies to, which is a backwards edge bought
for one dispatch dict. `scripts/` was not an option at all: the Dockerfile
copies `packages/`, `apps/` and `migrations/`, so nothing under `scripts/` is
in the deployed image for Railway to run.

Decision 54.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from boobs_api import misses
from boobs_observability import configure, logger
from boobs_reputation.evidence import rebuild
from boobs_schemas import db as database
from boobs_schemas.tables import ExecutionStat

log = logger(__name__)


async def retention() -> int:
    """Drop recall misses nobody has asked for since `misses.RETENTION` ago.

    Overlap needs no lock. Two of these running at once issue the same
    idempotent range delete; the loser deletes the rows the winner already
    took, which is zero rows and no conflict. Any job added here that is *not*
    idempotent has to say so and bring its own guard -- Railway skipping a tick
    is protection against a slow run, not against two of them.
    """
    async with database.session() as session:
        removed = await misses.sweep(session)
        await session.commit()
    return removed


async def evidence() -> int:
    """Rebuild the least recently touched versions' evidence from source rows.

    The reconciliation half of decision 57. `recompute` folds new runs on to a
    stored checkpoint so a popular capability does not pay for its own history
    twice per run, and that fold is exact -- but "exact" is a claim about code,
    and decision 11 is a claim about the corpus. This is what keeps the second
    one true independently of the first: every version comes round to a full
    rescan of its immutable rows, and if a checkpoint had drifted for any
    reason at all -- a lost update between two workers reporting at once, a bug
    in the fold, a hand-written row -- the numbers are corrected without
    anybody having to notice they were wrong.

    It is also spec section 24's sweep. `recompute` re-evaluates quarantine, so
    a version whose last runs failed is withdrawn from recall on this clock
    even if nothing ever runs it again.

    Least-recently-updated first and a batch cap, so the job is bounded whatever
    the corpus grows to; `updated_at` is set by the rebuild, which makes the
    ordering a round robin without a cursor to store. Overlap is safe for
    retention's reason and one more: two of these compute the same answer from
    the same immutable rows.
    """
    async with database.session() as session:
        stale = (
            (
                await session.execute(
                    select(ExecutionStat.experience_version_id)
                    .order_by(ExecutionStat.updated_at)
                    .limit(REBUILD_BATCH)
                )
            )
            .scalars()
            .all()
        )
        for version_id in stale:
            await rebuild(session, version_id)
        await session.commit()
    return len(stale)


# How many versions one tick rebuilds. Small enough that a tick is short even
# when every version has a long history, large enough that a corpus of a few
# thousand versions comes all the way round in a day of hourly ticks. Raise it
# or add a second schedule before reaching for concurrency.
REBUILD_BATCH = 500

# Jobs are invoked by name and nothing else. Adding one is a line here and a
# second Railway service with its own schedule -- re-verification (spec 26/27),
# which actually re-runs artifacts, is the named next one, and it is "read some
# rows, do a thing, exit", which is the shape this already is.
JOBS: dict[str, Callable[[], Awaitable[int]]] = {
    "retention": retention,
    "evidence": evidence,
}


async def run(name: str) -> int:
    """Run one job by name and return how many rows it touched."""
    log.info("job_started", job=name)
    try:
        affected = await JOBS[name]()
    finally:
        # A cron service is expected to leave nothing open. Postgres counts an
        # abandoned pool against max_connections whether the process meant it
        # or not.
        await database.dispose()
    log.info("job_finished", job=name, affected=affected)
    return affected


def main() -> int:
    configure("80085-scheduler")
    wanted = sys.argv[1:]
    if len(wanted) != 1 or wanted[0] not in JOBS:
        # Loudly, on stderr, with a non-zero exit: a scheduler that shrugged at
        # a typo in a start command would look exactly like one that is working.
        print(  # noqa: T201 - this is the CLI's own usage line
            f"usage: 80085-scheduler <{'|'.join(sorted(JOBS))}>",
            file=sys.stderr,
        )
        return 2
    try:
        asyncio.run(run(wanted[0]))
    except Exception:
        # The traceback goes to stderr as well as the log line, because the
        # deployment log is where an operator looks first.
        log.exception("job_failed", job=wanted[0])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
