"""Verify a hosted 80085 MCP endpoint the way a real client would.

`curl` cannot meaningfully test an MCP server -- it speaks a session protocol,
not plain request/response. This opens a real MCP session, lists the tools,
and exercises recall with a supplied key.

    uv run python scripts/check_mcp.py --url https://mcp.80085.ai/mcp --key sk_80085_...
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {"recall_experience", "run_experience", "record_experience"}


def unwrap(result: Any) -> dict[str, Any]:
    payload = result.structured_content or {}
    return dict(payload.get("result", payload))


async def check(url: str, key: str, task: str) -> int:
    failures: list[str] = []

    def report(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'  ok   ' if ok else ' FAIL  '}] {name}{'' if ok else f' -- {detail}'}")
        if not ok:
            failures.append(name)

    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=300.0
    )
    try:
        async with (
            streamable_http_client(url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            report("session initialized", True)

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            report(
                "three tools exposed",
                names >= EXPECTED_TOOLS,
                f"got {sorted(names)}",
            )

            result = unwrap(
                await session.call_tool(
                    "recall_experience", {"task": task, "runtime": "python"}
                )
            )
            if "error" in result:
                report("recall_experience", False, str(result)[:300])
            else:
                matches = result.get("matches", [])
                report("recall_experience answered", True)
                for match in matches[:3]:
                    evidence = match["evidence"]
                    print(
                        f"           {match['recommendation']:9} "
                        f"rel={match['relevance']:.3f} "
                        f"runs={evidence['successful_runs']}  {match['goal'][:44]}"
                    )
                report("at least one match", bool(matches), "registry may be empty")
    except Exception as exc:  # noqa: BLE001 - this script reports, never raises
        report("connect", False, f"{type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("MCP endpoint is live and answering with the supplied key")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url", default=os.environ.get("BOOBS_MCP_URL", "http://localhost:8080/mcp")
    )
    parser.add_argument("--key", default=os.environ.get("BOOBS_API_KEY", ""))
    parser.add_argument("--task", default="turn comma separated tabular data into json records")
    args = parser.parse_args()

    if not args.key:
        print("--key (or BOOBS_API_KEY) is required", file=sys.stderr)
        return 2
    return asyncio.run(check(args.url, args.key, args.task))


if __name__ == "__main__":
    raise SystemExit(main())
