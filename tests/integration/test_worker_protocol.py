"""The worker is a new trust boundary, so it gets its own tests.

A worker runs off-platform and holds a key. Three things must be true:
its key must not be a general-purpose key, an ordinary agent must not be able
to impersonate a worker, and a worker must not be able to declare its own
success.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from boobs_security.keys import Scope
from tests.helpers import auth, bootstrap, record_experience

pytestmark = [pytest.mark.integration]

DIGEST = "sha256:" + "dd" * 32


async def worker_auth(api: httpx.AsyncClient, name: str) -> dict[str, str]:
    return auth(await bootstrap(api, f"{name}-org", name, [Scope.WORKER]))


async def test_a_worker_key_cannot_read_or_record(api: httpx.AsyncClient) -> None:
    """A leaked worker key must not expose the registry."""
    headers = await worker_auth(api, "narrow-worker")

    recall = await api.post("/v1/experiences/recall", headers=headers, json={"task": "anything"})
    assert recall.status_code == 403

    record = await api.post(
        "/v1/experiences",
        headers=headers,
        json={
            "goal": {"statement": "should not be allowed", "intent": "nope"},
            "artifact": {"type": "oci", "reference": f"registry.test/80085/nope@{DIGEST}"},
        },
    )
    assert record.status_code == 403


async def test_an_ordinary_agent_cannot_lease_work(api: httpx.AsyncClient) -> None:
    """Leasing is not an agent capability; it would expose other tenants' inputs."""
    key = await bootstrap(api, "not-a-worker-org", "ordinary-agent")
    response = await api.post(
        "/v1/worker/lease", headers=auth(key), json={"worker_id": "pretending"}
    )
    assert response.status_code == 403


async def test_lease_returns_null_when_the_queue_is_empty(api: httpx.AsyncClient) -> None:
    """An idle worker is the normal case, not an error.

    Drains first: the test database is shared across the session, so other
    tests legitimately leave queued work behind.
    """
    headers = await worker_auth(api, "idle-worker")

    for _ in range(50):
        response = await api.post("/v1/worker/lease", headers=headers, json={"worker_id": "idle-1"})
        assert response.status_code == 200
        if response.json()["job"] is None:
            break
    else:
        pytest.fail("queue never drained")

    # And it stays null rather than erroring on an empty queue.
    again = await api.post("/v1/worker/lease", headers=headers, json={"worker_id": "idle-1"})
    assert again.status_code == 200
    assert again.json()["job"] is None


async def test_a_worker_cannot_report_on_a_job_it_does_not_hold(
    api: httpx.AsyncClient,
) -> None:
    key = await bootstrap(api, "held-org", "held-agent")
    experience_id = await record_experience(api, key, "Held job capability", "held_job", DIGEST)
    run = await api.post(f"/v1/experiences/{experience_id}/execute", headers=auth(key), json={})
    execution_id = run.json()["execution_id"]

    holder = await worker_auth(api, "holder")
    leased = await api.post("/v1/worker/lease", headers=holder, json={"worker_id": "holder-1"})
    assert leased.json()["job"]["execution_id"] == execution_id

    thief = await worker_auth(api, "thief")
    stolen = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=thief,
        json={
            "worker_id": "thief-1",
            "status": "succeeded",
            "exit_code": 0,
            "duration_ms": 1,
        },
    )
    assert stolen.status_code == 403


async def test_the_api_verifies_the_result_the_worker_does_not(
    api: httpx.AsyncClient,
) -> None:
    """A worker reporting exit code 0 is a claim, not evidence.

    Here the worker reports success but produces output that fails the
    declared verifier. The run must be recorded as unverified, and the
    Experience must not be promoted.
    """
    key = await bootstrap(api, "honest-org", "honest-agent")
    experience_id = await record_experience(
        api,
        key,
        "Produce a JSON array of results",
        "produce_array",
        DIGEST,
        verification={
            "verifier": "json_schema",
            "config": {"file": "output.json", "schema": {"type": "array"}},
        },
    )
    run = await api.post(f"/v1/experiences/{experience_id}/execute", headers=auth(key), json={})
    execution_id = run.json()["execution_id"]

    headers = await worker_auth(api, "lying-worker")
    leased = await api.post("/v1/worker/lease", headers=headers, json={"worker_id": "liar-1"})
    assert leased.json()["job"]["execution_id"] == execution_id

    # Claims success, but the output is an object where an array was required.
    reported = await api.post(
        f"/v1/worker/executions/{execution_id}/result",
        headers=headers,
        json={
            "worker_id": "liar-1",
            "status": "succeeded",
            "exit_code": 0,
            "duration_ms": 5,
            "outputs": {
                "output.json": base64.b64encode(json.dumps({"not": "an array"}).encode()).decode()
            },
        },
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["verified"] is False

    detail: dict[str, Any] = (
        await api.get(f"/v1/experiences/{experience_id}", headers=auth(key))
    ).json()
    assert detail["verification_level"] == "unverified"
    assert detail["evidence"]["successful_runs"] == 0
    assert detail["evidence"]["failed_runs"] == 1
