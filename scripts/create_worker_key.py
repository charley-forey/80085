"""Mint an API key for an execution worker.

A worker key carries one scope: `worker:execute`. It can lease jobs and report
results, and nothing else -- it cannot recall, record, or read another
tenant's experiences. A leaked worker key does not expose the registry.

    uv run python scripts/create_worker_key.py
    uv run python scripts/create_worker_key.py --url https://api.example
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("BOOBS_API_URL", "http://localhost:8000"))
    parser.add_argument(
        "--token",
        default=os.environ.get("BOOBS_BOOTSTRAP_TOKEN", ""),
        help="BOOBS_BOOTSTRAP_TOKEN of the target deployment",
    )
    parser.add_argument("--name", default="worker")
    args = parser.parse_args()

    if not args.token:
        print("--token (or BOOBS_BOOTSTRAP_TOKEN) is required", file=sys.stderr)
        return 2

    response = httpx.post(
        f"{args.url}/v1/bootstrap",
        json={
            "organization": f"{args.name}-fleet",
            "agent": args.name,
            "token": args.token,
            "scopes": ["worker:execute"],
        },
        timeout=60.0,
    )
    if response.status_code != 201:
        print(f"failed ({response.status_code}): {response.text[:300]}", file=sys.stderr)
        return 1

    body = response.json()
    print(json.dumps(body, indent=2))
    print("\nRun a worker with:\n", file=sys.stderr)
    print(
        f"  BOOBS_API_URL={args.url} BOOBS_API_KEY={body['api_key']} uv run 80085-worker\n",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
