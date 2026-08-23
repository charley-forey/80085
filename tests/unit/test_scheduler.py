"""A cron that silently does nothing looks exactly like a cron that works.

Railway starts the scheduler with whatever string somebody typed into a start
command, and nothing checks that string until it reaches `main`. So the two
things worth pinning here are that a name it does not know is a non-zero exit
rather than a shrug, and that a job never runs by accident.

What the retention job actually deletes is a claim about a `WHERE` clause and
is asserted against a real database in
`tests/integration/test_retention_job.py`.
"""

from __future__ import annotations

import sys

import pytest

from boobs_api import scheduler


@pytest.mark.parametrize(
    "argv",
    [
        [],  # no job named at all
        ["retentionn"],  # a typo in the Railway start command
        ["retention", "staleness"],  # two jobs, one process
        [""],
    ],
)
def test_an_unknown_job_exits_non_zero_and_runs_nothing(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(scheduler, "JOBS", {"retention": lambda: ran.append("retention")})
    monkeypatch.setattr(sys, "argv", ["80085-scheduler", *argv])

    assert scheduler.main() == 2
    assert ran == [], "an unrecognised job name must not fall through to a real one"


def test_a_job_that_raises_exits_one_rather_than_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit code is the whole alarm. A job that failed must not report success."""

    async def explode() -> int:
        raise RuntimeError("postgres said no")

    monkeypatch.setattr(scheduler, "JOBS", {"boom": explode})
    monkeypatch.setattr(sys, "argv", ["80085-scheduler", "boom"])

    assert scheduler.main() == 1


def test_a_job_that_works_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fine() -> int:
        return 7

    async def recorded(name: str, affected: int) -> None:
        """The heartbeat writes to a real database and this is a unit test.

        Stubbed rather than made non-fatal in `run`: a heartbeat that could not
        be written is a genuine problem -- it is the same database the job just
        committed to -- and swallowing it would report success while the row
        that proves the job ran silently went missing. `job_runs` not existing
        is exactly how this surfaced.
        """

    monkeypatch.setattr(scheduler, "JOBS", {"fine": fine})
    monkeypatch.setattr(scheduler, "_record", recorded)
    monkeypatch.setattr(sys, "argv", ["80085-scheduler", "fine"])

    assert scheduler.main() == 0


def test_the_evidence_sweep_is_a_registered_job() -> None:
    """Spec section 24's other half. `recompute` withdraws what rots when a run
    is reported; this is what withdraws it when nothing is ever run again --
    and what keeps decision 11 true independently of the fold."""
    assert "evidence" in scheduler.JOBS


def test_retention_is_a_registered_job() -> None:
    """The name in `infrastructure/railway/scheduler.md` and in the start
    command is this string; a rename that misses one of them is a cron that
    exits 2 forever, at 03:00, where nobody is looking."""
    assert "retention" in scheduler.JOBS
