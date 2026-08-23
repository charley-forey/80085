"""MCP server (spec sections 13 and 14).

MCP is the easiest path for an agent to use 80085, so the tool surface is
deliberately tiny: ask, run, contribute. The server is an HTTP client of the
API like any other caller -- it has no database access and no privileged path.

The integration instruction it exists to make true:

    Before solving a non-trivial task from scratch, ask 80085 whether a
    verified executable Experience already exists.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from boobs_common.config import settings

mcp = MCPServer(
    "80085",
    instructions=(
        "Before solving a non-trivial task from scratch, call recall_experience "
        "to check whether a verified executable solution already exists."
    ),
)


def _client() -> httpx.AsyncClient:
    key = os.environ.get("BOOBS_API_KEY", settings().boobs_api_key)
    if not key:
        raise RuntimeError("BOOBS_API_KEY is not set; the MCP server cannot call the API")
    return httpx.AsyncClient(
        base_url=os.environ.get("BOOBS_API_URL", settings().api_base_url),
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(120.0),
    )


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with _client() as client:
        response = await client.post(path, json=payload)
        if response.status_code >= 400:
            return {"error": response.status_code, "detail": response.text[:1000]}
        return dict(response.json())


@mcp.tool()
async def recall_experience(
    task: str,
    runtime: str | None = None,
    runtime_version: str | None = None,
    os_name: str = "linux",
    architecture: str = "amd64",
    network: bool = False,
    limit: int = 5,
) -> dict[str, Any]:
    """Ask whether a verified, executable solution for this task already exists.

    Call this BEFORE solving a non-trivial task from scratch. Returns ranked
    matches with evidence: success rate, verified run count, and whether the
    artifact is compatible with your environment. A `recommendation` of "use"
    means running it is very likely cheaper than rebuilding it.
    """
    return await _post(
        "/v1/experiences/recall",
        {
            "task": task,
            "context": {
                "runtime": runtime,
                "runtime_version": runtime_version,
                "os": os_name,
                "architecture": architecture,
            },
            "constraints": {"network": network},
            "limit": limit,
        },
    )


@mcp.tool()
async def run_experience(
    experience_id: str,
    inputs: dict[str, str] | None = None,
    version: int | None = None,
    wait_seconds: int = 120,
) -> dict[str, Any]:
    """Execute an exact Experience version in an isolated sandbox.

    `inputs` maps filename to UTF-8 text, staged into the sandbox working
    directory. Outputs come back the same way. The result includes an
    independent verification outcome -- not the artifact's own claim.
    """
    encoded = {
        name: base64.b64encode(content.encode()).decode()
        for name, content in (inputs or {}).items()
    }
    result = await _post(
        f"/v1/experiences/{experience_id}/execute",
        {"inputs": encoded, "version": version, "wait_seconds": wait_seconds},
    )
    outputs = result.get("outputs") or {}
    if isinstance(outputs, dict):
        result["outputs"] = {
            name: base64.b64decode(blob).decode(errors="replace") for name, blob in outputs.items()
        }
    return result


@mcp.tool()
async def record_experience(
    goal: str,
    intent: str,
    artifact_reference: str,
    command: list[str] | None = None,
    verifier: str | None = None,
    verifier_config: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    visibility: str = "organization",
    runtime: str | None = None,
    runtime_version: str | None = None,
) -> dict[str, Any]:
    """Contribute a solution you just proved works, so the next agent can reuse it.

    `artifact_reference` must be digest-pinned (repository@sha256:...) -- a tag
    would let the bytes change under the evidence collected for them.
    Declaring a verifier is what turns future runs into evidence rather than
    claims.
    """
    payload: dict[str, Any] = {
        "goal": {"statement": goal, "intent": intent, "tags": tags or []},
        "artifact": {"type": "oci", "reference": artifact_reference},
        "command": command or [],
        "environment": {
            "os": "linux",
            "architecture": "amd64",
            "runtime": runtime,
            "runtime_version": runtime_version,
        },
        "visibility": visibility,
    }
    if verifier:
        payload["verification"] = {"verifier": verifier, "config": verifier_config or {}}
    return await _post("/v1/experiences", payload)


TRANSPORTS = ("stdio", "sse", "streamable-http")


def main() -> None:
    transport = os.environ.get("BOOBS_MCP_TRANSPORT", "stdio")
    if transport not in TRANSPORTS:
        raise SystemExit(f"BOOBS_MCP_TRANSPORT must be one of {TRANSPORTS}, got {transport!r}")
    if transport == "sse":
        mcp.run(transport="sse")
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
