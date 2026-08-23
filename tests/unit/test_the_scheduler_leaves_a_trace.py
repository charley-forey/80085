"""A cron service that stopped firing raises no alarm.

Railway reports a crashed deployment when a job exits non-zero -- but only for
a service that still exists. The failure worth catching is quieter: a cron
service never created, deleted, or given a schedule that does not fire. Nothing
crashes, `/v1/ready` stays green, recall and execution carry on working, and
evidence simply stops being reconciled.

`scripts/smoke.py` could not check it. The obvious candidate,
`execution_stats.updated_at`, is written by the execution path too -- so a
recent value proves only that somebody ran something. That is a check which
passes for the wrong reason, and this project has now found that same shape in
the egress suite, the corpus count, and the benchmark.

So the scheduler leaves a mark of its own, and these pin the two properties
that make the mark worth trusting: it is written when the job succeeds, and it
is *not* written when the job raises.
"""

from __future__ import annotations

import asyncio

import pytest

from boobs_api import scheduler


def test_a_finished_job_records_when_it_finished() -> None:
    recorded: list[tuple[str, int]] = []

    async def fake_record(name: str, affected: int) -> None:
        recorded.append((name, affected))

    async def job() -> int:
        return 7

    original_jobs, original_record = scheduler.JOBS, scheduler._record
    scheduler.JOBS = {"probe": job}
    scheduler._record = fake_record  # type: ignore[assignment]
    try:
        assert asyncio.run(scheduler.run("probe")) == 7
    finally:
        scheduler.JOBS, scheduler._record = original_jobs, original_record  # type: ignore[assignment]

    assert recorded == [("probe", 7)], "a successful job must leave a heartbeat"


def test_a_job_that_raises_records_nothing() -> None:
    """The property that makes the heartbeat mean anything.

    A mark written unconditionally would say "the cron service is alive" while
    every tick failed -- reporting health on the strength of having been asked.
    """
    recorded: list[tuple[str, int]] = []

    async def fake_record(name: str, affected: int) -> None:
        recorded.append((name, affected))

    async def job() -> int:
        raise RuntimeError("the job blew up")

    original_jobs, original_record = scheduler.JOBS, scheduler._record
    scheduler.JOBS = {"probe": job}
    scheduler._record = fake_record  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="blew up"):
            asyncio.run(scheduler.run("probe"))
    finally:
        scheduler.JOBS, scheduler._record = original_jobs, original_record  # type: ignore[assignment]

    assert recorded == [], "a failed job must not leave a heartbeat saying it succeeded"


def test_every_scheduled_job_is_one_smoke_watches() -> None:
    """Adding a job to the scheduler without a staleness window would leave it
    unwatched, which is the same silence this whole change exists to end."""
    import ast
    from pathlib import Path

    smoke = Path(__file__).resolve().parents[2] / "scripts" / "smoke.py"
    tree = ast.parse(smoke.read_text(encoding="utf-8"), filename=str(smoke))
    watched: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "JOB_STALE_AFTER" for t in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            watched = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}

    assert watched, "smoke.py no longer defines JOB_STALE_AFTER"
    assert set(scheduler.JOBS) == watched, (
        f"scheduler runs {sorted(scheduler.JOBS)} but smoke watches {sorted(watched)}; "
        "a job nobody watches is a job that can stop without anyone noticing"
    )
