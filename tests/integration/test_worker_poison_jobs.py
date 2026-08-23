"""A queued job naming a row that does not exist must not be retried forever.

This exists because a queue that outlived its database once wedged the worker:
every slot was busy retrying jobs that could never succeed, and real
executions sat at "queued" until they timed out.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]


async def test_missing_execution_row_is_abandoned_not_retried(database_url: str) -> None:
    from boobs_worker.main import execute_experience

    assert await execute_experience({}, "exec_does_not_exist") == "abandoned"


async def test_worker_declares_a_bounded_retry_budget() -> None:
    from boobs_worker.main import WorkerSettings

    assert WorkerSettings.max_tries <= 3
