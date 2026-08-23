"""Seed a running 80085 with two agents and the example Experiences.

Creates two organizations on purpose: the product claim is cross-agent reuse,
so a single-tenant seed would prove nothing.

    uv run python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DIGESTS = ROOT / "capabilities" / "digests.json"
API = os.environ.get("BOOBS_API_URL", "http://localhost:8000")
BOOTSTRAP = os.environ.get("BOOBS_BOOTSTRAP_TOKEN", "dev-bootstrap-change-me")

EXPERIENCES: dict[str, dict[str, Any]] = {
    "csv_to_json": {
        "goal": {
            "statement": "Convert a CSV file into a normalized JSON array of objects",
            "intent": "csv_to_json",
            "tags": ["csv", "json", "conversion", "tabular"],
        },
        "command": ["python", "/app/main.py", "input.csv", "output.json"],
        "verification": {
            "verifier": "json_schema",
            "config": {"file": "output.json", "schema": {"type": "array"}},
        },
    },
    "json_to_csv": {
        "goal": {
            "statement": "Convert a JSON array of objects into a CSV file",
            "intent": "json_to_csv",
            "tags": ["json", "csv", "conversion", "tabular"],
        },
        "command": ["python", "/app/main.py", "input.json", "output.csv"],
        "verification": {"verifier": "exit_code", "config": {"expected": 0}},
    },
    "json_validate": {
        "goal": {
            "statement": "Validate a JSON document against a JSON Schema and report errors",
            "intent": "validate_json",
            "tags": ["json", "schema", "validation"],
        },
        "command": ["python", "/app/main.py", "input.json", "schema.json", "result.json"],
        "verification": {
            "verifier": "json_schema",
            "config": {
                "file": "result.json",
                "schema": {"type": "object", "required": ["valid", "errors"]},
            },
        },
    },
}


async def bootstrap(client: httpx.AsyncClient, organization: str, agent: str) -> str:
    response = await client.post(
        "/v1/bootstrap",
        json={"organization": organization, "agent": agent, "token": BOOTSTRAP},
    )
    response.raise_for_status()
    return str(response.json()["api_key"])


async def main() -> int:
    if not DIGESTS.is_file():
        raise SystemExit("run scripts/build_capabilities.py first (no capabilities/digests.json)")
    digests = json.loads(DIGESTS.read_text())

    async with httpx.AsyncClient(base_url=API, timeout=60.0) as client:
        producer_key = await bootstrap(client, "acme-research", "agent-a")
        consumer_key = await bootstrap(client, "globex-labs", "agent-b")

        recorded = []
        for name, spec in EXPERIENCES.items():
            reference = digests.get(name)
            if not reference:
                print(f"skipping {name}: not built")
                continue
            response = await client.post(
                "/v1/experiences",
                headers={"Authorization": f"Bearer {producer_key}"},
                json={
                    **spec,
                    "artifact": {"type": "oci", "reference": reference},
                    "environment": {
                        "os": "linux",
                        "architecture": "amd64",
                        "runtime": "python",
                        "runtime_version": "3.13",
                    },
                    "constraints": {"network": False},
                    # Public so a different organization can discover it: that
                    # is the whole point of the registry.
                    "visibility": "public",
                },
            )
            response.raise_for_status()
            recorded.append((name, response.json()["experience_id"]))

    print(
        json.dumps(
            {
                "producer_key": producer_key,
                "consumer_key": consumer_key,
                "experiences": dict(recorded),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
