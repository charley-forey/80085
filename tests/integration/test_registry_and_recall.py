"""Database-level guarantees: immutability, tenancy, and hard filters.

These run against real Postgres because every property under test is enforced
by Postgres -- a trigger, an array containment operator, a tsvector index. A
mocked database would test nothing.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.helpers import auth, bootstrap

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]

DIGEST = "sha256:" + "11" * 32
PINNED = f"registry.test/80085/demo@{DIGEST}"


def ids(response: httpx.Response) -> set[str]:
    """Recall runs against a database shared by the whole test session, so a
    filter test asserts about its own experience, not about an empty result."""
    return {match["experience_id"] for match in response.json()["matches"]}


def payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "goal": {
            "statement": "Convert a CSV file into a JSON array",
            "intent": "csv_to_json",
            "tags": ["csv", "json"],
        },
        "artifact": {"type": "oci", "reference": PINNED},
        "command": ["python", "/app/main.py"],
        "environment": {
            "os": "linux",
            "architecture": "amd64",
            "runtime": "python",
            "runtime_version": "3.13",
        },
        "constraints": {"network": False},
        "visibility": "public",
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------------ artifacts


async def test_tagged_reference_is_refused_at_the_boundary(api: httpx.AsyncClient) -> None:
    key = await bootstrap(api, "pin-org", "pin-agent")
    response = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json=payload(artifact={"type": "oci", "reference": "registry.test/demo:latest"}),
    )
    assert response.status_code == 422
    assert "pinned" in response.text


async def test_identical_bytes_are_one_artifact(api: httpx.AsyncClient) -> None:
    key = await bootstrap(api, "dedupe-org", "dedupe-agent")
    first = await api.post("/v1/experiences", headers=auth(key), json=payload())
    second = await api.post("/v1/experiences", headers=auth(key), json=payload())
    assert first.json()["artifact_digest"] == second.json()["artifact_digest"] == DIGEST


# ------------------------------------------------------------------- tenancy


async def test_private_experience_is_invisible_to_another_tenant(
    api: httpx.AsyncClient,
) -> None:
    owner = await bootstrap(api, "private-org", "private-agent")
    stranger = await bootstrap(api, "stranger-org", "stranger-agent")

    created = await api.post(
        "/v1/experiences", headers=auth(owner), json=payload(visibility="private")
    )
    experience_id = created.json()["experience_id"]

    direct = await api.get(f"/v1/experiences/{experience_id}", headers=auth(stranger))
    assert direct.status_code == 403

    recalled = await api.post(
        "/v1/experiences/recall",
        headers=auth(stranger),
        json={"task": "Convert a CSV file into a JSON array"},
    )
    assert experience_id not in ids(recalled)


async def test_public_experience_is_visible_across_tenants(api: httpx.AsyncClient) -> None:
    owner = await bootstrap(api, "public-org", "public-agent")
    stranger = await bootstrap(api, "public-reader-org", "public-reader")
    created = await api.post(
        "/v1/experiences", headers=auth(owner), json=payload(visibility="public")
    )
    response = await api.get(
        f"/v1/experiences/{created.json()['experience_id']}", headers=auth(stranger)
    )
    assert response.status_code == 200


# -------------------------------------------------------------- hard filters


async def test_incompatible_architecture_is_filtered_before_ranking(
    api: httpx.AsyncClient,
) -> None:
    key = await bootstrap(api, "arch-org", "arch-agent")
    created = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json=payload(environment={"os": "linux", "architecture": "arm64", "runtime": "python"}),
    )
    response = await api.post(
        "/v1/experiences/recall",
        headers=auth(key),
        json={
            "task": "Convert a CSV file into a JSON array",
            "context": {"os": "linux", "architecture": "amd64"},
        },
    )
    assert created.json()["experience_id"] not in ids(response)


async def test_network_requiring_experience_is_hidden_from_offline_callers(
    api: httpx.AsyncClient,
) -> None:
    key = await bootstrap(api, "net-org", "net-agent")
    # Distinctive wording: the network filter is under test here, not tie-breaking
    # between several identically-worded experiences in a shared test database.
    task = "Fetch currency exchange rates from a remote pricing API"
    created = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json=payload(
            goal={"statement": task, "intent": "fetch_rates", "tags": ["currency", "rates"]},
            constraints={"network": True},
        ),
    )
    experience_id = created.json()["experience_id"]

    offline = await api.post(
        "/v1/experiences/recall",
        headers=auth(key),
        json={"task": task, "constraints": {"network": False}},
    )
    assert experience_id not in ids(offline)

    online = await api.post(
        "/v1/experiences/recall",
        headers=auth(key),
        json={"task": task, "constraints": {"network": True}},
    )
    assert experience_id in ids(online)


async def test_required_capability_must_be_offered_by_the_caller(
    api: httpx.AsyncClient,
) -> None:
    key = await bootstrap(api, "cap-org", "cap-agent")
    task = "Transcribe an audio recording into timestamped text using a GPU"
    created = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json=payload(
            goal={"statement": task, "intent": "audio_to_text", "tags": ["audio", "transcribe"]},
            constraints={"network": False, "required_capabilities": ["gpu"]},
        ),
    )
    experience_id = created.json()["experience_id"]

    without = await api.post("/v1/experiences/recall", headers=auth(key), json={"task": task})
    assert experience_id not in ids(without)

    with_gpu = await api.post(
        "/v1/experiences/recall",
        headers=auth(key),
        json={
            "task": task,
            "constraints": {"network": False, "required_capabilities": ["gpu", "cuda"]},
        },
    )
    assert experience_id in ids(with_gpu)


# --------------------------------------------------------------- immutability


async def test_recorded_versions_cannot_be_rewritten(api: httpx.AsyncClient, db: Any) -> None:
    """Evidence is attached to a version. If the version could change, the
    evidence would be about something that no longer exists."""
    key = await bootstrap(api, "immutable-org", "immutable-agent")
    created = await api.post("/v1/experiences", headers=auth(key), json=payload())
    version_id = created.json()["experience_version_id"]

    with pytest.raises(Exception, match="append-only"):
        await db.execute(
            text("UPDATE experience_versions SET command = '{}' WHERE id = :id"),
            {"id": version_id},
        )
    await db.rollback()

    with pytest.raises(Exception, match="append-only"):
        await db.execute(text("DELETE FROM experience_versions WHERE id = :id"), {"id": version_id})
    await db.rollback()


async def test_authentication_is_required_and_bad_keys_are_refused(
    api: httpx.AsyncClient,
) -> None:
    assert (await api.post("/v1/experiences/recall", json={"task": "anything"})).status_code == 401
    forged = auth("sk_80085_" + "a" * 40)
    assert (
        await api.post("/v1/experiences/recall", headers=forged, json={"task": "anything"})
    ).status_code == 401
