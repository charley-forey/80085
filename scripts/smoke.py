"""Post-deploy smoke test (spec section 53).

    A deployment command exiting 0 is not evidence that anything works.

This exercises the real loop against a real deployment: record, execute,
verify, recall from a second organization. It creates only its own data and
tells you exactly which step failed.

    uv run python scripts/smoke.py --url https://api.80085.ai --token "$BOOBS_BOOTSTRAP_TOKEN"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DIGESTS = ROOT / "capabilities" / "digests.json"
CSV = b"track,bpm\nAcid Trax,128\n"

PASS = "  ok   "
FAIL = " FAIL  "


class Smoke:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"[{PASS if ok else FAIL}] {name}{'' if ok else f' -- {detail}'}")
        if not ok:
            self.failures.append(name)
        return ok


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="BOOBS_BOOTSTRAP_TOKEN")
    parser.add_argument(
        "--reference", help="digest-pinned artifact; defaults to capabilities/digests.json"
    )
    parser.add_argument("--wait", type=int, default=180)
    args = parser.parse_args()

    reference = args.reference
    if not reference:
        if not DIGESTS.is_file():
            print("no --reference and no capabilities/digests.json", file=sys.stderr)
            return 2
        reference = json.loads(DIGESTS.read_text())["csv_to_json"]

    # Every run writes into the target registry, so it labels its own data and
    # recalls a phrase only this run could have recorded. Without that, run N
    # finds run N-1's identical Experience and the check proves nothing.
    run_id = secrets.token_hex(3)
    statement = f"Convert a CSV file into a normalized JSON array of objects (smoke {run_id})"

    smoke = Smoke()
    print(f"smoke testing {args.url}  [run {run_id}]\n")

    async with httpx.AsyncClient(base_url=args.url, timeout=float(args.wait + 30)) as client:
        health = await client.get("/v1/health")
        smoke.check("health", health.status_code == 200, health.text[:200])

        ready = await client.get("/v1/ready")
        body = ready.json() if ready.status_code < 500 else {}
        smoke.check("ready", ready.status_code == 200, ready.text[:300])
        for service, ok in (body.get("checks") or {}).items():
            smoke.check(f"  dependency: {service}", bool(ok))

        if smoke.failures:
            print("\ndependencies are not healthy; stopping before writing data")
            return 1

        producer = await client.post(
            "/v1/bootstrap",
            json={
                "organization": f"smoke-producer-{run_id}",
                "agent": "smoke-a",
                "token": args.token,
            },
        )
        if not smoke.check("bootstrap producer", producer.status_code == 201, producer.text[:200]):
            return 1
        consumer = await client.post(
            "/v1/bootstrap",
            json={
                "organization": f"smoke-consumer-{run_id}",
                "agent": "smoke-b",
                "token": args.token,
            },
        )
        smoke.check("bootstrap consumer", consumer.status_code == 201, consumer.text[:200])

        key_a = producer.json()["api_key"]
        key_b = consumer.json()["api_key"]
        auth_a = {"Authorization": f"Bearer {key_a}"}
        auth_b = {"Authorization": f"Bearer {key_b}"}

        recorded = await client.post(
            "/v1/experiences",
            headers=auth_a,
            json={
                "goal": {
                    "statement": statement,
                    "intent": "csv_to_json",
                    "tags": ["smoke", "csv", "json", run_id],
                },
                "artifact": {"type": "oci", "reference": reference},
                "command": ["python", "/app/main.py", "input.csv", "output.json"],
                "environment": {
                    "os": "linux",
                    "architecture": "amd64",
                    "runtime": "python",
                    "runtime_version": "3.13",
                },
                "constraints": {"network": False},
                "verification": {
                    "verifier": "json_schema",
                    "config": {"file": "output.json", "schema": {"type": "array"}},
                },
                "visibility": "public",
            },
        )
        if not smoke.check("record experience", recorded.status_code == 201, recorded.text[:300]):
            return 1
        experience_id = recorded.json()["experience_id"]

        tagged = await client.post(
            "/v1/experiences",
            headers=auth_a,
            json={
                "goal": {"statement": "should never be accepted", "intent": "bad"},
                "artifact": {"type": "oci", "reference": "registry.example/thing:latest"},
            },
        )
        smoke.check("unpinned artifact is refused", tagged.status_code == 422, tagged.text[:200])

        run = await client.post(
            f"/v1/experiences/{experience_id}/execute",
            headers=auth_a,
            json={
                "inputs": {"input.csv": base64.b64encode(CSV).decode()},
                "wait_seconds": args.wait,
            },
        )
        result = run.json()
        if not smoke.check(
            "execute reaches a terminal state",
            result.get("status") in {"succeeded", "failed", "timeout"},
            f"status={result.get('status')} -- is a worker running and connected?",
        ):
            return 1
        smoke.check("execution succeeded", result.get("status") == "succeeded", str(result)[:300])
        smoke.check(
            "verifier proved the output",
            bool((result.get("verification") or {}).get("passed")),
            str(result.get("verification"))[:300],
        )

        events = await client.get(f"/v1/executions/{result['execution_id']}/events", headers=auth_a)
        kinds = (
            [event["event_type"] for event in events.json()] if events.status_code == 200 else []
        )
        smoke.check("event stream recorded the run", "execution.completed" in kinds, str(kinds))

        recall = await client.post(
            "/v1/experiences/recall",
            headers=auth_b,
            json={
                # Recall the phrase only this run recorded, so a registry full
                # of older smoke runs cannot make this pass or fail by accident.
                "task": statement,
                "context": {"runtime": "python"},
                "limit": 20,
            },
        )
        matches = recall.json().get("matches", []) if recall.status_code == 200 else []
        found = next((m for m in matches if m["experience_id"] == experience_id), None)
        smoke.check(
            "a second organization recalls it by paraphrase", found is not None, recall.text[:300]
        )
        if found:
            smoke.check(
                "evidence reflects the verified run",
                found["evidence"]["successful_runs"] >= 1,
                str(found["evidence"]),
            )

        leaked = await client.get(f"/v1/executions/{result['execution_id']}", headers=auth_b)
        smoke.check("another tenant cannot read the execution", leaked.status_code == 404)

    print()
    if smoke.failures:
        print(f"FAILED: {len(smoke.failures)} check(s): {', '.join(smoke.failures)}")
        return 1
    print("all checks passed -- the reuse loop works on this deployment")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
