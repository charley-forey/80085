"""THE test (spec sections 36 and 54).

    Agent A solves task X and records an executable solution.
    Verification proves it worked.
    Agent B -- a different organization, a different key, no shared context --
    describes the same task in different words, finds A's solution, runs the
    exact pinned version, and a verifier proves it worked again.
    Agent C independently discovers the same solution.
    The evidence for all three runs is visible.

If this passes, the product thesis holds: reuse was cheaper than reinvention,
and nobody had to take anyone's word for it. If it fails, nothing else in the
repository matters.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("docker", "worker")]

INPUT_CSV = b"track,bpm,key\nAcid Trax,128,Am\nStrings of Life,122,Fm\nPhuture,130,Gm\n"

# Agent A's words.
TASK_A = "Convert a CSV file into a normalized JSON array of objects"
# Agent B's words for the same job. Deliberately different phrasing: if recall
# only matched on identical strings, the product would be useless.
TASK_B = "I need to turn tabular comma-separated data into JSON records"
# Agent C's words, different again.
TASK_C = "parse a csv export and give me json"


async def bootstrap(api: httpx.AsyncClient, organization: str, agent: str) -> str:
    response = await api.post(
        "/v1/bootstrap",
        json={"organization": organization, "agent": agent, "token": "test-bootstrap"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["api_key"])


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_agent_b_reuses_agent_a_solution_without_agent_a(
    api: httpx.AsyncClient, digests: dict[str, str]
) -> None:
    reference = digests["csv_to_json"]

    # --- three independent tenants -------------------------------------
    key_a = await bootstrap(api, "acme-research", "agent-a")
    key_b = await bootstrap(api, "globex-labs", "agent-b")
    key_c = await bootstrap(api, "initech-data", "agent-c")
    assert key_a != key_b != key_c

    # --- 1. Agent A records the solution it just proved -----------------
    recorded = await api.post(
        "/v1/experiences",
        headers=auth(key_a),
        json={
            "goal": {
                "statement": TASK_A,
                "intent": "csv_to_json",
                "tags": ["csv", "json", "conversion"],
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
    assert recorded.status_code == 201, recorded.text
    experience_id = recorded.json()["experience_id"]
    version = recorded.json()["version"]
    digest = recorded.json()["artifact_digest"]
    assert digest.startswith("sha256:")
    assert recorded.json()["verification_level"] == "unverified"  # nothing proven yet

    # --- 2. Agent A executes it; verification proves it worked ----------
    run_a = await api.post(
        f"/v1/experiences/{experience_id}/execute",
        headers=auth(key_a),
        json={"inputs": {"input.csv": base64.b64encode(INPUT_CSV).decode()}, "wait_seconds": 180},
    )
    assert run_a.status_code == 200, run_a.text
    body_a = run_a.json()
    assert body_a["status"] == "succeeded", body_a
    assert body_a["verification"]["passed"] is True
    assert body_a["verification"]["level"] == "proven"
    assert body_a["artifact_digest"] == digest

    rows = json.loads(base64.b64decode(body_a["outputs"]["output.json"]))
    assert [row["track"] for row in rows] == ["Acid Trax", "Strings of Life", "Phuture"]

    # --- 3. Agent B asks, in its own words, having never met Agent A ----
    recall_b = await api.post(
        "/v1/experiences/recall",
        headers=auth(key_b),
        json={
            "task": TASK_B,
            "context": {"runtime": "python", "runtime_version": "3.13"},
            "constraints": {"network": False},
        },
    )
    assert recall_b.status_code == 200, recall_b.text
    matches = recall_b.json()["matches"]
    assert matches, "agent B found nothing; reuse cannot beat reinvention"

    top = matches[0]
    assert top["experience_id"] == experience_id
    assert top["recommendation"] in {"use", "consider"}
    assert top["evidence"]["successful_runs"] == 1
    assert top["compatibility"] == "high"

    # Agent B has no access to Agent A's run: only the capability crosses the
    # tenant boundary, never the data or the session.
    leaked = await api.get(f"/v1/executions/{body_a['execution_id']}", headers=auth(key_b))
    assert leaked.status_code == 404

    # --- 4. Agent B runs the exact version A recorded ------------------
    run_b = await api.post(
        f"/v1/experiences/{top['experience_id']}/execute",
        headers=auth(key_b),
        json={
            "version": top["version"],
            "inputs": {"input.csv": base64.b64encode(b"a,b\n1,2\n").decode()},
            "wait_seconds": 180,
        },
    )
    assert run_b.status_code == 200, run_b.text
    body_b = run_b.json()
    assert body_b["status"] == "succeeded", body_b
    assert body_b["verification"]["passed"] is True
    # Same bytes, not merely the same name.
    assert body_b["artifact_digest"] == digest
    assert body_b["version"] == version
    assert json.loads(base64.b64decode(body_b["outputs"]["output.json"])) == [{"a": "1", "b": "2"}]

    # --- 5. Agent C independently discovers the same solution ----------
    recall_c = await api.post(
        "/v1/experiences/recall",
        headers=auth(key_c),
        json={"task": TASK_C, "context": {"runtime": "python"}},
    )
    assert recall_c.status_code == 200, recall_c.text
    top_c = recall_c.json()["matches"][0]
    assert top_c["experience_id"] == experience_id

    # --- 6. Evidence reflects all of it -------------------------------
    evidence = top_c["evidence"]
    assert evidence["successful_runs"] == 2
    assert evidence["failed_runs"] == 0
    assert evidence["distinct_organizations"] == 2, "cross-agent reuse is not being counted"
    assert evidence["last_verified_at"] is not None
    assert 0.0 < evidence["confidence"] < 1.0  # honest about thin evidence
    assert top_c["recommendation"] in {"use", "consider"}

    # The Experience itself is now proven, not merely claimed.
    detail = await api.get(f"/v1/experiences/{experience_id}", headers=auth(key_c))
    assert detail.json()["status"] == "verified"
    assert detail.json()["verification_level"] == "proven"


async def test_the_event_stream_records_what_happened(
    api: httpx.AsyncClient, digests: dict[str, str]
) -> None:
    """Derived metadata must be regenerable from event history (section 20)."""
    key = await bootstrap(api, "events-org", "agent-events")
    recorded = await api.post(
        "/v1/experiences",
        headers=auth(key),
        json={
            "goal": {"statement": "Convert CSV to JSON", "intent": "csv_to_json"},
            "artifact": {"type": "oci", "reference": digests["csv_to_json"]},
            "command": ["python", "/app/main.py", "input.csv", "output.json"],
            "verification": {"verifier": "exit_code", "config": {"expected": 0}},
        },
    )
    experience_id = recorded.json()["experience_id"]
    run = await api.post(
        f"/v1/experiences/{experience_id}/execute",
        headers=auth(key),
        json={"inputs": {"input.csv": base64.b64encode(INPUT_CSV).decode()}, "wait_seconds": 180},
    )
    assert run.json()["status"] == "succeeded", run.text

    events = await api.get(f"/v1/executions/{run.json()['execution_id']}/events", headers=auth(key))
    assert events.status_code == 200
    kinds = [event["event_type"] for event in events.json()]
    assert kinds[0] == "execution.started"
    assert "execution.completed" in kinds
    assert "verification.completed" in kinds
    assert [event["sequence"] for event in events.json()] == sorted(
        event["sequence"] for event in events.json()
    )
