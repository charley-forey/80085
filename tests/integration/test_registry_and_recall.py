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
NEVER_RECORDED = "exp_" + "0" * 32
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

    # 404, and byte-identical to the answer for an id that was never recorded.
    # This used to be 403, which made the read path an existence oracle: a
    # stranger holding an id from a log or a screenshot could confirm it was
    # real without ever being allowed to see a field of it. Asserted against a
    # real row rather than a mock, because the claim is that the row is there.
    direct = await api.get(f"/v1/experiences/{experience_id}", headers=auth(stranger))
    absent = await api.get(f"/v1/experiences/{NEVER_RECORDED}", headers=auth(stranger))
    assert direct.status_code == absent.status_code == 404, direct.text
    assert direct.json()["error"] == absent.json()["error"]
    assert direct.json()["detail"].replace(experience_id, "ID") == absent.json()["detail"].replace(
        NEVER_RECORDED, "ID"
    )

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


async def test_recall_is_open_but_a_bad_key_is_still_refused(
    api: httpx.AsyncClient,
) -> None:
    """Absent credentials read as nobody; broken ones are refused.

    Recall deliberately needs no key -- a shared brain nobody can query is not
    shared. But only an *absent* credential is anonymous. A forged, malformed
    or revoked key still fails, because silently downgrading a bad key to
    anonymous would turn a caller's expired credential into a permission change
    they never asked for (see get_principal_or_anonymous).
    """
    open_recall = await api.post("/v1/experiences/recall", json={"task": "anything"})
    assert open_recall.status_code == 200

    forged = auth("sk_80085_" + "a" * 40)
    assert (
        await api.post("/v1/experiences/recall", headers=forged, json={"task": "anything"})
    ).status_code == 401


async def test_writing_and_reading_an_execution_still_require_a_key(
    api: httpx.AsyncClient,
) -> None:
    """Opening recall opened recall, and nothing else.

    An execution may contain the caller's own data, so it is never readable
    without a credential -- the anonymous principal carries EXPERIENCES_READ
    and nothing more.
    """
    assert (await api.get("/v1/executions/exe_missing")).status_code == 401
    forged = auth("sk_80085_" + "a" * 40)
    assert (await api.get("/v1/executions/exe_missing", headers=forged)).status_code == 401
