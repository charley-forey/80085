"""Control vs treatment (spec sections 37 and 38).

    CONTROL   -- no 80085: build the executable artifact from scratch, run it,
                 verify the output.
    TREATMENT -- with 80085: ask, run the pinned version that already exists,
                 verify the output.

Both arms end at the same place: a verified correct result. The primary metric
is TIME TO SUCCESSFUL OUTCOME.

What this measures honestly: the cost of producing and running a *verified
executable artifact*. What it does not measure: an LLM's token and tool-call
cost, which needs a real agent harness and real model credentials. Those
columns stay empty rather than invented -- see docs/benchmarks.md.

    uv run python benchmarks/run.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIGESTS = ROOT / "capabilities" / "digests.json"
EXAMPLES = ROOT / "capabilities" / "examples"
REGISTRY = os.environ.get("ARTIFACT_REGISTRY", "localhost:5000")
REPEATS = int(os.environ.get("BENCHMARK_REPEATS", "3"))

# The benchmark gets its own queue database. A worker left over from another
# environment must not be able to pick up jobs for rows it cannot see.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/2")

CSV = b"track,bpm,key\nAcid Trax,128,Am\nStrings of Life,122,Fm\n"
JSON_ROWS = json.dumps([{"track": "Acid Trax", "bpm": 128}]).encode()
SCHEMA = json.dumps({"type": "array"}).encode()


@dataclass(frozen=True)
class Task:
    name: str
    goal: str
    intent: str
    command: list[str]
    inputs: dict[str, bytes]
    verifier: dict[str, Any]
    # What an agent that has never seen this registry would type.
    paraphrase: str


TASKS = [
    Task(
        name="csv_to_json",
        goal="Convert a CSV file into a normalized JSON array of objects",
        intent="csv_to_json",
        command=["python", "/app/main.py", "input.csv", "output.json"],
        inputs={"input.csv": CSV},
        verifier={
            "verifier": "json_schema",
            "config": {"file": "output.json", "schema": {"type": "array"}},
        },
        paraphrase="turn comma separated tabular data into json records",
    ),
    Task(
        name="json_to_csv",
        goal="Convert a JSON array of objects into a CSV file",
        intent="json_to_csv",
        command=["python", "/app/main.py", "input.json", "output.csv"],
        inputs={"input.json": JSON_ROWS},
        verifier={"verifier": "exit_code", "config": {"expected": 0}},
        paraphrase="export json records as a spreadsheet-friendly csv",
    ),
    Task(
        name="json_validate",
        goal="Validate a JSON document against a JSON Schema and report errors",
        intent="validate_json",
        command=["python", "/app/main.py", "input.json", "schema.json", "result.json"],
        inputs={"input.json": JSON_ROWS, "schema.json": SCHEMA},
        verifier={
            "verifier": "json_schema",
            "config": {
                "file": "result.json",
                "schema": {"type": "object", "required": ["valid", "errors"]},
            },
        },
        paraphrase="check a json document conforms to a schema",
    ),
]


# ------------------------------------------------------------------- control


async def control(task: Task) -> tuple[float, bool]:
    """No registry: build the artifact, then run and verify it yourself."""
    from boobs_domain.entities import VerificationSpec
    from boobs_domain.protocols import SandboxRequest
    from boobs_execution import DockerOciRuntime
    from boobs_verification.verifiers import RegistryVerifier

    started = time.monotonic()
    repository = f"{REGISTRY}/80085-control/{task.name}"
    tag = f"{repository}:bench"

    # --no-cache: an agent solving this from scratch has no layer cache for a
    # solution that did not exist a moment ago.
    build = subprocess.run(
        ["docker", "build", "--no-cache", "--quiet", "-t", tag, str(EXAMPLES / task.name)],
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        return time.monotonic() - started, False
    subprocess.run(["docker", "push", "--quiet", tag], capture_output=True, text=True)
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{json .RepoDigests}}", tag],
        capture_output=True,
        text=True,
    )
    reference = next(
        (ref for ref in json.loads(inspect.stdout or "[]") if ref.startswith(repository + "@")),
        None,
    )
    if reference is None:
        return time.monotonic() - started, False

    result = await DockerOciRuntime().execute(
        SandboxRequest(
            execution_id=f"bench-control-{task.name}-{int(time.time() * 1000)}",
            image=reference,
            command=task.command,
            input_files=task.inputs,
            cpu=2,
            memory_mb=1024,
            tmpfs_mb=512,
            timeout_seconds=120,
            pids=128,
            max_output_bytes=1_048_576,
        )
    )
    outcome = await RegistryVerifier().verify(
        result, VerificationSpec(verifier=task.verifier["verifier"], config=task.verifier["config"])
    )
    return time.monotonic() - started, outcome.passed


# ----------------------------------------------------------------- treatment


async def treatment(client: httpx.AsyncClient, key: str, task: Task) -> tuple[float, bool]:
    """With the registry: ask for it, run the pinned version, read the verdict."""
    started = time.monotonic()
    headers = {"Authorization": f"Bearer {key}"}

    recall = await client.post(
        "/v1/experiences/recall",
        headers=headers,
        json={"task": task.paraphrase, "context": {"runtime": "python"}},
    )
    matches = recall.json().get("matches", [])
    if not matches:
        return time.monotonic() - started, False

    top = matches[0]
    run = await client.post(
        f"/v1/experiences/{top['experience_id']}/execute",
        headers=headers,
        json={
            "version": top["version"],
            "inputs": {name: base64.b64encode(blob).decode() for name, blob in task.inputs.items()},
            "wait_seconds": 180,
        },
    )
    body = run.json()
    passed = bool((body.get("verification") or {}).get("passed"))
    return time.monotonic() - started, passed


# ------------------------------------------------------------------- harness


async def seed(client: httpx.AsyncClient, digests: dict[str, str]) -> tuple[str, str]:
    """A producer records the Experiences; a *different* org consumes them."""
    token = os.environ.get("BOOBS_BOOTSTRAP_TOKEN", "dev-bootstrap-change-me")

    async def account(organization: str, agent: str) -> str:
        response = await client.post(
            "/v1/bootstrap",
            json={"organization": organization, "agent": agent, "token": token},
        )
        response.raise_for_status()
        return str(response.json()["api_key"])

    producer = await account("benchmark-producer", "agent-producer")
    consumer = await account("benchmark-consumer", "agent-consumer")

    for task in TASKS:
        response = await client.post(
            "/v1/experiences",
            headers={"Authorization": f"Bearer {producer}"},
            json={
                "goal": {"statement": task.goal, "intent": task.intent, "tags": [task.name]},
                "artifact": {"type": "oci", "reference": digests[task.name]},
                "command": task.command,
                "environment": {
                    "os": "linux",
                    "architecture": "amd64",
                    "runtime": "python",
                    "runtime_version": "3.13",
                },
                "constraints": {"network": False},
                "verification": task.verifier,
                "visibility": "public",
            },
        )
        response.raise_for_status()
    return producer, consumer


def table(rows: list[dict[str, Any]]) -> str:
    header = (
        f"{'task':<16}{'control':>10}{'treatment':>12}{'speedup':>10}"
        f"{'ctrl ok':>10}{'treat ok':>10}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['task']:<16}{row['control']:>9.2f}s{row['treatment']:>11.2f}s"
            f"{row['speedup']:>9.1f}x"
            f"{'yes' if row['control_verified'] else 'NO':>10}"
            f"{'yes' if row['treatment_verified'] else 'NO':>10}"
        )
    total_control = sum(row["control"] for row in rows)
    total_treatment = sum(row["treatment"] for row in rows)
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<16}{total_control:>9.2f}s{total_treatment:>11.2f}s"
        f"{total_control / max(total_treatment, 1e-9):>9.1f}x"
    )
    return "\n".join(lines)


async def main() -> int:
    if not DIGESTS.is_file():
        raise SystemExit("run `uv run python scripts/build_capabilities.py` first")
    digests = json.loads(DIGESTS.read_text())

    from boobs_api.main import create_app
    from boobs_common import storage

    await storage.ensure_bucket()

    log = (ROOT / "benchmarks" / "worker.log").open("wb")
    worker = subprocess.Popen(
        [sys.executable, "-m", "arq", "boobs_worker.main.WorkerSettings"],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://benchmark", timeout=300.0
        ) as client:
            _, consumer = await seed(client, digests)

            rows = []
            for task in TASKS:
                controls: list[float] = []
                treatments: list[float] = []
                control_ok = treatment_ok = True
                for _ in range(REPEATS):
                    seconds, ok = await control(task)
                    controls.append(seconds)
                    control_ok &= ok
                    seconds, ok = await treatment(client, consumer, task)
                    treatments.append(seconds)
                    treatment_ok &= ok
                rows.append(
                    {
                        "task": task.name,
                        "control": statistics.median(controls),
                        "treatment": statistics.median(treatments),
                        "speedup": statistics.median(controls) / statistics.median(treatments),
                        # Reported per arm: a single combined flag hides which
                        # side failed, which is the only thing worth knowing.
                        "control_verified": control_ok,
                        "treatment_verified": treatment_ok,
                    }
                )
                print(f"  {task.name} done", flush=True)

    finally:
        worker.terminate()
        try:
            worker.wait(timeout=20)
        except subprocess.TimeoutExpired:
            worker.kill()
        log.close()

    print(f"\nTIME TO SUCCESSFUL OUTCOME (median of {REPEATS})\n")
    print(table(rows))
    print(
        "\ncontrol   = build the artifact from scratch, run it, verify it"
        "\ntreatment = recall an existing verified Experience, run it, verify it"
        "\ntokens and tool calls are not measured here; see docs/benchmarks.md"
    )
    (ROOT / "benchmarks" / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
