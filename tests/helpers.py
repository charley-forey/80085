"""Small helpers shared by the integration and e2e suites."""

from __future__ import annotations

from typing import Any

import httpx

BOOTSTRAP_TOKEN = "test-bootstrap"


async def bootstrap(
    api: httpx.AsyncClient, organization: str, agent: str, scopes: list[str] | None = None
) -> str:
    payload: dict[str, Any] = {
        "organization": organization,
        "agent": agent,
        "token": BOOTSTRAP_TOKEN,
    }
    if scopes is not None:
        payload["scopes"] = scopes
    response = await api.post("/v1/bootstrap", json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["api_key"])


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def record_experience(
    api: httpx.AsyncClient,
    key: str,
    statement: str,
    intent: str,
    digest: str,
    **overrides: Any,
) -> str:
    body: dict[str, Any] = {
        "goal": {"statement": statement, "intent": intent, "tags": []},
        "artifact": {"type": "oci", "reference": f"registry.test/80085/{intent}@{digest}"},
        "command": ["python", "/app/main.py"],
        "environment": {"os": "linux", "architecture": "amd64", "runtime": "python"},
        "visibility": "public",
    }
    body.update(overrides)
    response = await api.post("/v1/experiences", headers=auth(key), json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["experience_id"])
