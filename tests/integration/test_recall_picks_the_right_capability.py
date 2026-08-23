"""Recall must return the right capability, not the popular one.

A registry that answers "convert JSON to CSV" with a heavily-used CSV-to-JSON
Experience is worse than useless: the agent runs it, it fails, and reuse costs
more than reinvention. This file exists because that is exactly what happened
once, and the ranking was changed so it cannot happen again.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]

DIGEST_A = "sha256:" + "aa" * 32
DIGEST_B = "sha256:" + "bb" * 32


async def bootstrap(api: httpx.AsyncClient, organization: str, agent: str) -> str:
    response = await api.post(
        "/v1/bootstrap",
        json={"organization": organization, "agent": agent, "token": "test-bootstrap"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["api_key"])


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def record(
    api: httpx.AsyncClient, key: str, statement: str, intent: str, digest: str, tags: list[str]
) -> str:
    response = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json={
            "goal": {"statement": statement, "intent": intent, "tags": tags},
            "artifact": {"type": "oci", "reference": f"registry.test/80085/{intent}@{digest}"},
            "command": ["python", "/app/main.py"],
            "environment": {"os": "linux", "architecture": "amd64", "runtime": "python"},
            "visibility": "public",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["experience_id"])


async def top_match(api: httpx.AsyncClient, key: str, task: str) -> dict[str, object] | None:
    response = await api.post(
        "/v1/experiences/recall",
        headers=auth(key),
        json={"task": task, "context": {"runtime": "python"}},
    )
    assert response.status_code == 200, response.text
    matches = response.json()["matches"]
    return matches[0] if matches else None


async def test_direction_of_the_conversion_is_respected(api: httpx.AsyncClient) -> None:
    key = await bootstrap(api, "direction-org", "direction-agent")
    forward = await record(
        api,
        key,
        "Convert a CSV file into a normalized JSON array of objects",
        "csv_to_json",
        DIGEST_A,
        ["csv", "json"],
    )
    backward = await record(
        api,
        key,
        "Convert a JSON array of objects into a CSV file",
        "json_to_csv",
        DIGEST_B,
        ["json", "csv"],
    )

    match = await top_match(api, key, "turn comma separated tabular data into json records")
    assert match is not None and match["experience_id"] == forward

    match = await top_match(api, key, "export json records as a csv file")
    assert match is not None and match["experience_id"] == backward


async def test_an_unrelated_task_returns_nothing_rather_than_the_nearest_thing(
    api: httpx.AsyncClient,
) -> None:
    """An empty answer is a correct answer (spec section 57)."""
    key = await bootstrap(api, "unrelated-org", "unrelated-agent")
    await record(
        api,
        key,
        "Convert a CSV file into a normalized JSON array of objects",
        "csv_to_json",
        DIGEST_A,
        ["csv", "json"],
    )
    match = await top_match(
        api, key, "provision a kubernetes cluster and configure ingress with mutual TLS"
    )
    assert match is None


async def test_a_brand_new_experience_is_considered_not_recommended(
    api: httpx.AsyncClient,
) -> None:
    """Relevance is not evidence. Nothing is 'use' until something proved it."""
    key = await bootstrap(api, "fresh-org", "fresh-agent")
    await record(
        api,
        key,
        "Convert a CSV file into a normalized JSON array of objects",
        "csv_to_json",
        DIGEST_A,
        ["csv", "json"],
    )
    match = await top_match(api, key, "Convert a CSV file into a normalized JSON array of objects")
    assert match is not None
    assert match["evidence"]["successful_runs"] == 0
    assert match["recommendation"] == "consider"
