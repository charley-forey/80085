"""Run the whole corpus as a second organization, so its evidence is corroborated.

The product claim is cross-agent reuse, and since decision 41 nothing is
recommended as `use` until two distinct organizations have proven it. Seeding
records every capability under one org and the smoke test runs one of them;
everything else sits at `consider` with `distinct_organizations: 1` forever
unless somebody else actually runs it. This is that somebody.

For every capability in the manifest with a fixture, as the consumer key:
find the live Experience, skip it if a second org already ran it, execute it
with its fixture inputs, and print what came back. Verification happens on
the API when the worker reports, and the hourly evidence job folds the run
into the score, so `use` appears within the hour of a clean run.

Executions are limited per address, ten an hour. The script sleeps to the
next window when it hits that, or run shards from two hosts:

    BOOBS_API_KEY=<consumer> uv run python scripts/corroborate.py --shard 1/2
    BOOBS_API_KEY=<consumer> uv run python scripts/corroborate.py --shard 2/2

`--audit` executes nothing and prints each capability's recommendation,
confidence, runs and organizations -- the corpus scoreboard.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "capabilities" / "manifest.json"
FIXTURES = ROOT / "capabilities" / "fixtures"


async def find(client: httpx.AsyncClient, statement: str) -> dict[str, Any] | None:
    """The live Experience whose goal is exactly this statement, or None."""
    response = await client.post("/v1/experiences/recall", json={"task": statement, "limit": 10})
    response.raise_for_status()
    for match in response.json().get("matches", []):
        if match.get("goal") == statement:
            return dict(match)
    return None


def inputs_for(name: str) -> dict[str, str]:
    folder = FIXTURES / name / "inputs"
    if not folder.is_dir():
        return {}
    return {f.name: base64.b64encode(f.read_bytes()).decode() for f in sorted(folder.iterdir())}


async def run_one(
    client: httpx.AsyncClient,
    name: str,
    statement: str,
    wait: int,
    sleep_on_limit: bool,
    audit: bool = False,
) -> str:
    found = await find(client, statement)
    if not found:
        return "missing   not in the live registry"
    experience_id = found["experience_id"]

    current = await client.get(f"/v1/experiences/{experience_id}")
    current.raise_for_status()
    evidence = current.json().get("evidence") or {}
    orgs = int(evidence.get("distinct_organizations") or 0)
    if audit:
        return (
            f"{found.get('recommendation', '?'):9} {found.get('confidence', 0):6.1%}  "
            f"runs={evidence.get('successful_runs', 0)} orgs={orgs}"
        )
    if orgs >= 2:
        return f"skip      already corroborated ({found.get('recommendation')})"

    inputs = inputs_for(name)
    if not inputs:
        return "skip      no fixture inputs"

    while True:
        run = await client.post(
            f"/v1/experiences/{experience_id}/execute",
            json={"inputs": inputs, "wait_seconds": wait},
        )
        if run.status_code == 429 and sleep_on_limit:
            pause = 3600 - int(time.time()) % 3600 + 5
            print(f"          rate limited; sleeping {pause}s to the next window", flush=True)
            await asyncio.sleep(pause)
            continue
        break
    if run.status_code == 429:
        return "limited   ten executions an hour per address; rerun next hour"
    if run.status_code >= 400:
        return f"error     HTTP {run.status_code} {run.text[:160]}"

    result = run.json()
    status_ = result.get("status")
    verdict = result.get("verification") or {}
    passed = verdict.get("passed")
    if status_ == "succeeded" and passed:
        return f"ok        {result.get('duration_ms')}ms  verified by {verdict.get('verifier')}"
    detail = result.get("error") or (result.get("stderr") or "")[-200:]
    return f"{status_ or '?':9} exit={result.get('exit_code')} verified={passed} {detail}".rstrip()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("BOOBS_API_URL", "https://api.80085.ai"))
    parser.add_argument("--key", default=os.environ.get("BOOBS_API_KEY", ""))
    parser.add_argument("--wait", type=int, default=150, help="seconds to block per run")
    parser.add_argument("--only", help="comma-separated capability names")
    parser.add_argument("--shard", default="1/1", help="i/n: run the i-th of n interleaved slices")
    parser.add_argument(
        "--no-sleep", action="store_true", help="exit on the rate limit instead of waiting"
    )
    parser.add_argument(
        "--audit", action="store_true", help="report recommendation and evidence; execute nothing"
    )
    args = parser.parse_args()
    if not args.key:
        print("need --key or BOOBS_API_KEY (the consumer organization's key)", file=sys.stderr)
        return 2

    corpus: dict[str, dict[str, Any]] = json.loads(MANIFEST.read_text(encoding="utf-8"))[
        "capabilities"
    ]
    names = sorted(corpus)
    if args.only:
        names = [n for n in names if n in set(args.only.split(","))]
    i, n = (int(x) for x in args.shard.split("/"))
    names = names[i - 1 :: n]

    failures = 0
    async with httpx.AsyncClient(
        base_url=args.url,
        headers={"Authorization": f"Bearer {args.key}", "Accept": "application/json"},
        timeout=args.wait + 60,
    ) as client:
        for name in names:
            statement = corpus[name]["goal"]["statement"]
            try:
                line = await run_one(
                    client, name, statement, args.wait, not args.no_sleep, args.audit
                )
            except httpx.HTTPError as exc:
                line = f"error     {exc}"
            if not line.startswith(("ok", "skip", "use")):
                failures += 1
            print(f"{name:22} {line}", flush=True)
            if args.audit:
                await asyncio.sleep(1.1)  # recall is sixty a minute per address

    what = "not yet use" if args.audit else "not ok"
    print(
        f"\n{len(names)} {'audited' if args.audit else 'attempted'}, {failures} {what}", flush=True
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
