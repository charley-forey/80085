"""Seed a running 80085 with two agents and the whole capability corpus.

Creates two organizations on purpose: the product claim is cross-agent reuse,
so a single-tenant seed would prove nothing.

The Experiences themselves live in capabilities/manifest.json, which is also
what tests/unit/test_capabilities.py runs against -- one description of the
corpus, so a goal statement and the code that satisfies it cannot drift apart.

    uv run python scripts/build_capabilities.py   # first: digests
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
MANIFEST = ROOT / "capabilities" / "manifest.json"
API = os.environ.get("BOOBS_API_URL", "http://localhost:8000")
BOOTSTRAP = os.environ.get("BOOBS_BOOTSTRAP_TOKEN", "dev-bootstrap-change-me")


async def bootstrap(client: httpx.AsyncClient, organization: str, agent: str, env: str) -> str:
    """The organization's key: an existing one if you have it, or a new one.

    `/v1/bootstrap` creates a *new* organization on every call, so seeding a
    live deployment twice used to duplicate the entire corpus under a second
    identity -- production ended up holding thirteen copies of one capability,
    which crowded the exact match for a task out of its own top ten. Pass
    BOOBS_PRODUCER_KEY and BOOBS_CONSUMER_KEY to seed as the organizations
    that already exist.
    """
    existing = os.environ.get(env, "").strip()
    if existing:
        print(f"reusing {organization} from {env}")
        return existing
    response = await client.post(
        "/v1/bootstrap",
        json={"organization": organization, "agent": agent, "token": BOOTSTRAP},
    )
    response.raise_for_status()
    return str(response.json()["api_key"])


async def already_recorded(client: httpx.AsyncClient, key: str, statement: str) -> str | None:
    """The id of a live Experience with exactly this goal, if there is one.

    Recording is not idempotent -- and should not be, because two organizations
    solving the same problem their own way is the point. Re-running the seeder
    is a different thing, and this is what keeps it from being a contribution.
    """
    response = await client.post(
        "/v1/experiences/recall",
        headers={"Authorization": f"Bearer {key}"},
        json={"task": statement, "limit": 20},
    )
    if response.status_code != 200:
        return None
    for match in response.json().get("matches", []):
        if match.get("goal") == statement:
            return str(match["experience_id"])
    return None


async def main() -> int:
    if not DIGESTS.is_file():
        raise SystemExit("run scripts/build_capabilities.py first (no capabilities/digests.json)")
    digests = json.loads(DIGESTS.read_text())
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    defaults: dict[str, Any] = manifest["defaults"]
    corpus: dict[str, dict[str, Any]] = manifest["capabilities"]

    async with httpx.AsyncClient(base_url=API, timeout=60.0) as client:
        producer_key = await bootstrap(client, "acme-research", "agent-a", "BOOBS_PRODUCER_KEY")
        consumer_key = await bootstrap(client, "globex-labs", "agent-b", "BOOBS_CONSUMER_KEY")

        recorded = []
        for name, spec in corpus.items():
            reference = digests.get(name)
            if not reference:
                print(f"skipping {name}: not built")
                continue
            existing = await already_recorded(client, producer_key, spec["goal"]["statement"])
            if existing:
                print(f"skipping {name}: already recorded as {existing}")
                recorded.append((name, existing))
                continue
            response = await client.post(
                "/v1/experiences",
                headers={"Authorization": f"Bearer {producer_key}"},
                json={
                    **spec,
                    "artifact": {"type": "oci", "reference": reference},
                    "environment": defaults["environment"],
                    "constraints": defaults["constraints"],
                    # Public so a different organization can discover it: that
                    # is the whole point of the registry.
                    "visibility": defaults["visibility"],
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
