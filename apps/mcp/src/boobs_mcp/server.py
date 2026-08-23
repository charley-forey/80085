"""MCP server (spec sections 13 and 14).

MCP is the easiest path for an agent to use 80085, so the tool surface is
deliberately tiny: ask, run, contribute.

The integration instruction it exists to make true:

    Before solving a non-trivial task from scratch, ask 80085 whether a
    verified executable Experience already exists.

## Credentials

This server holds no API key of its own. It runs in one of two modes:

* **hosted** (`streamable-http`) -- each caller sends its own 80085 API key as
  `Authorization: Bearer sk_80085_...`, and the server forwards it. One
  deployment serves every tenant, nobody shares a credential, and the API
  stays the single authority on who may do what. The header is never treated
  as an identity assertion here; it is passed through and the API decides.
* **local** (`stdio`) -- one user, key from `BOOBS_API_KEY`.

A hosted server with a single shared key would let any caller act as its
owner, which is why that is not an option.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from mcp.server.mcpserver import Context, MCPServer

# This package deliberately depends on nothing from the workspace. An agent
# installs it straight from the repo with
#     uvx --from git+<repo>#subdirectory=apps/mcp 80085-mcp
# and a workspace-only dependency like 80085-common would make that
# unresolvable, because it is not on PyPI. Both settings it used to supply are
# read from the environment anyway.
DEFAULT_API_URL = "https://api.80085.ai"

mcp = MCPServer(
    "80085",
    # Both halves of this string are load-bearing, so neither is safe to trim.
    #
    # The first sentence is the install story: the site used to ask people to
    # paste it into a system prompt, and that step was removed once `initialize`
    # was shown to deliver it on connect. Cutting it silently reintroduces a
    # manual step nobody is told about any more.
    #
    # The second is legal notice. Recall needs no key and keys mint without
    # signup, so there is no point at which a caller is shown terms -- the
    # handshake is the only moment an MCP client is told what binds it.
    instructions=(
        "Before solving a non-trivial task from scratch, call recall_experience "
        "to check whether a verified executable solution already exists.\n\n"
        "Query and execute freely. Do not bulk-extract, redistribute, or train "
        "on the corpus: https://80085.ai/TERMS.md. These terms bind whoever you "
        "are acting for."
    ),
)

TRANSPORTS = ("stdio", "sse", "streamable-http")


class MissingKey(RuntimeError):
    """Raised when neither the caller nor the environment supplied a key."""


def _api_key(ctx: Context | None, *, required: bool = True) -> str | None:
    """The caller's key if this is a hosted request, else the local one.

    `required=False` for recall, which is answerable without any credential --
    an agent that has just discovered this server should be able to ask it
    something before deciding whether to sign up for anything.
    """
    headers = getattr(ctx, "headers", None) if ctx is not None else None
    if headers:
        supplied = headers.get("authorization") or headers.get("Authorization")
        if supplied:
            return supplied if supplied.lower().startswith("bearer ") else f"Bearer {supplied}"

    key = os.environ.get("BOOBS_API_KEY", "")
    if not key:
        if not required:
            return None
        raise MissingKey(
            "No 80085 API key. Send 'Authorization: Bearer sk_80085_...' with the "
            "request, or set BOOBS_API_KEY when running this server locally."
        )
    return f"Bearer {key}"


def _client(ctx: Context | None, *, required: bool = True) -> httpx.AsyncClient:
    key = _api_key(ctx, required=required)
    return httpx.AsyncClient(
        base_url=os.environ.get("BOOBS_API_URL", DEFAULT_API_URL),
        headers={"Authorization": key} if key else {},
        timeout=httpx.Timeout(300.0),
    )


async def _post(
    ctx: Context | None, path: str, payload: dict[str, Any], *, required: bool = True
) -> dict[str, Any]:
    try:
        async with _client(ctx, required=required) as client:
            response = await client.post(path, json=payload)
    except MissingKey as exc:
        return {"error": "unauthenticated", "detail": str(exc)}
    if response.status_code >= 400:
        return {"error": response.status_code, "detail": response.text[:1000]}
    return dict(response.json())


@mcp.tool()
async def recall_experience(
    task: str,
    ctx: Context,
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
    means running it is very likely cheaper than rebuilding it. An empty list
    means no verified solution exists -- solve the task yourself, then record it.

    Needs no API key. Without one you see public Experiences, which is most of
    them; with one you also see your own organization's.
    """
    return await _post(
        ctx,
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
        required=False,
    )


@mcp.tool()
async def run_experience(
    experience_id: str,
    ctx: Context,
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
        ctx,
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
    ctx: Context,
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
    return await _post(ctx, "/v1/experiences", payload)


def main() -> None:
    transport = os.environ.get("BOOBS_MCP_TRANSPORT", "stdio")
    if transport not in TRANSPORTS:
        raise SystemExit(f"BOOBS_MCP_TRANSPORT must be one of {TRANSPORTS}, got {transport!r}")

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    # Hosted: bind what the platform gives us.
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 - a container must bind all interfaces
    port = int(os.environ.get("PORT", "8080"))
    if transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="streamable-http", host=host, port=port, stateless_http=True)


if __name__ == "__main__":
    main()
