"""The agent benchmark's verdict must come from the workspace, not the agent.

Both arms are timed, and a timed arm that could report its own success would
make the whole benchmark a measurement of how willing a model is to claim it
finished. So `verified()` runs the harness's own check inside the container
afterwards and hands it to the same verifier the platform uses.

The property under test is the one that keeps the numbers meaning anything:
an agent that does nothing fails, and only a real output file passes.
"""

from __future__ import annotations

import pytest

from benchmarks.agent import CHECKS, Workspace, verified
from benchmarks.run import TASKS


def test_every_task_has_a_harness_check() -> None:
    """A task with no check would silently pass every arm."""
    assert {task.name for task in TASKS} == set(CHECKS)


@pytest.mark.integration
@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.name)
async def test_an_agent_that_does_nothing_does_not_pass(task, docker: None) -> None:
    with Workspace(task, "test") as workspace:
        assert await verified(workspace, task) is False


@pytest.mark.integration
async def test_a_real_output_passes(docker: None) -> None:
    task = next(task for task in TASKS if task.name == "csv_to_json")
    with Workspace(task, "test") as workspace:
        # What a working solution leaves behind, and nothing else.
        _, code = workspace.sh(
            'python -c "import csv,json;'
            "json.dump(list(csv.DictReader(open('input.csv'))), open('output.json','w'))\""
        )
        assert code == 0
        assert await verified(workspace, task) is True
