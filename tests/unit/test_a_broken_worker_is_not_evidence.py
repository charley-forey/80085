"""A worker that cannot run the artifact must not blame the artifact.

`run_job` used to catch every exception and return `FAILED`, on the strength of
a comment that read "a runtime failure is a failed run". It is not. A failed
`docker pull`, a daemon that is not there, a filter that cannot be installed --
none of these say anything about whether the Experience works, and reporting
them as failed runs lowers the confidence of a solution that may be perfectly
good.

This is not hypothetical. A dev worker on a laptop joined the production queue,
failed every pull with a Windows NT status (`0xC0000142`), and wrote those
failures into the evidence of whatever it happened to claim. The queue uses
`FOR UPDATE SKIP LOCKED`, so a worker that fails in milliseconds wins *more*
leases than a healthy one that takes seconds to run a container: the broken
worker poisoned the corpus faster than the working one could prove it right.

So there are two properties here, and they are different:

  * an artifact that runs and fails is evidence, and is reported;
  * a runtime that cannot run it is not, and is not reported at all.
"""

from __future__ import annotations

import asyncio

import pytest

from boobs_common.errors import ExecutionFailed, RuntimeUnavailable
from boobs_domain.enums import ExecutionStatus
from boobs_worker import main as worker

JOB = {
    "execution_id": "exec_test",
    "image": "registry.example/thing@sha256:" + "0" * 64,
    "command": ["python", "main.py"],
    "inputs": {},
    "tier": None,
    "network": False,
}


class _Runtime:
    """Stands in for the sandbox and raises whatever the test asks for."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def execute(self, request: object) -> object:
        raise self.error


def _run(error: BaseException) -> object:
    original = worker.runtime
    worker.runtime = _Runtime(error)  # type: ignore[assignment]
    try:
        return asyncio.run(worker.run_job(dict(JOB)))
    finally:
        worker.runtime = original


def test_a_runtime_that_cannot_run_it_does_not_report_a_failure() -> None:
    """The exact shape of the production incident: a pull that never ran."""
    with pytest.raises(RuntimeUnavailable):
        _run(RuntimeUnavailable("docker pull failed (3221225794): "))


def test_an_artifact_that_fails_is_still_reported_as_failed() -> None:
    """The other half. Suppressing real failures would be the opposite bug, and
    a corpus that cannot record a failure is worth no more than one that
    records failures that never happened."""
    result = _run(ExecutionFailed("the artifact exited 1"))
    assert result.status is ExecutionStatus.FAILED  # type: ignore[attr-defined]
    assert "exited 1" in str(result.error)  # type: ignore[attr-defined]


def test_runtime_unavailable_is_not_an_execution_failure() -> None:
    """If it were a subclass, every existing `except ExecutionFailed` would go
    on treating a broken worker as a broken artifact, and this whole
    distinction would be decorative."""
    assert not issubclass(RuntimeUnavailable, ExecutionFailed)


def test_a_worker_that_cannot_run_anything_gives_up() -> None:
    """Staying in the pool is worse than exiting: SKIP LOCKED means a
    fast-failing worker out-competes a healthy one for every job."""
    assert worker.MAX_RUNTIME_FAILURES >= 1
