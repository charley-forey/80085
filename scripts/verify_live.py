"""Is what is deployed the thing we think is deployed?

Twice tonight a deploy succeeded on the right commit and served stale words,
because the copy exists in three places and only two were rewritten. Twice a
feature passed its tests and was unreachable, because the API had it and the MCP
surface did not. Both were found by looking at what is served rather than at
what was committed, and neither was found by a test.

So this checks the deployed surfaces, from outside, the way a stranger meets
them. It asserts nothing about the repository.

    BOOBS_API_KEY=<any key> uv run python scripts/verify_live.py
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx

API = os.environ.get("BOOBS_API_URL", "https://api.80085.ai")
MCP = os.environ.get("BOOBS_MCP_URL", "https://mcp.80085.ai/mcp")
SITE = os.environ.get("BOOBS_SITE_URL", "https://80085.ai")

# What the current copy says. If a surface does not carry these, it is serving
# an older story -- which is invisible from the repository and from the tests.
CURRENT = "stops guessing about your data"
OLD = ("second thoughts", "shared brain")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


async def main() -> int:
    key = os.environ.get("BOOBS_API_KEY")
    head = {"Authorization": f"Bearer {key}"} if key else {}

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        print("\nAPI")
        health = await http.get(f"{API}/v1/health")
        check("health", health.status_code == 200)

        ready = await http.get(f"{API}/v1/ready")
        body = ready.json() if ready.status_code == 200 else {}
        check("ready", bool(body.get("ready")), json.dumps(body.get("checks", {})))
        workers = body.get("workers", {})
        age = workers.get("last_lease_age_seconds")
        check(
            "worker attached",
            age is not None,
            f"last lease {age}s ago, {body.get('queued_executions')} queued",
        )

        print("\nTHE LOOP  (the product)")
        if not key:
            check("questions endpoint", False, "BOOBS_API_KEY not set, skipped")
        else:
            need = "verify_live probe: which timezone the settlement cutoff uses"
            asked = await http.post(f"{API}/v1/questions", headers=head, json={"need": need})
            check("record a halt", asked.status_code == 201, asked.text[:60])
            qid = asked.json().get("question_id") if asked.status_code == 201 else None

            if qid:
                answered = await http.post(
                    f"{API}/v1/questions/{qid}/answer",
                    headers=head,
                    json={"body": "UTC, always.", "answered_by": "verify_live"},
                )
                check("answer it", answered.status_code == 201, answered.text[:60])
                aid = answered.json().get("answer_id") if answered.status_code == 201 else None

                again = await http.post(f"{API}/v1/questions", headers=head, json={"need": need})
                served = (again.json() or {}).get("answer") if again.status_code == 201 else None
                check("the same question comes back answered", bool(served))

                if aid:
                    ok = await http.post(
                        f"{API}/v1/answers/{aid}/verify",
                        headers=head,
                        json={"verified_by": "verify_live"},
                    )
                    check("verify an answer", ok.status_code == 200, ok.text[:60])

            for path in (
                "/v1/questions/unanswered",
                "/v1/questions/stale",
                "/v1/questions/convergence",
                "/v1/answers/awaiting-verification",
            ):
                got = await http.get(f"{API}{path}", headers=head)
                check(f"GET {path}", got.status_code == 200, got.text[:50])

            made = await http.post(f"{API}/v1/keys", params={"label": "verify-live"})
            founder = made.json() if made.status_code == 201 else {}
            check(
                "self-serve org can provision",
                "agents:provision" in founder.get("scopes", []),
                str(founder.get("scopes", [])),
            )
            if founder.get("api_key"):
                colleague = await http.post(
                    f"{API}/v1/agents",
                    headers={"Authorization": f"Bearer {founder['api_key']}"},
                    json={"name": "verify-live-colleague"},
                )
                check("add a colleague", colleague.status_code == 201, colleague.text[:60])

        print("\nMCP")
        init = await http.post(
            MCP,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "verify", "version": "1"},
                },
            },
        )
        check("mcp reachable", init.status_code == 200, f"HTTP {init.status_code}")
        session = init.headers.get("mcp-session-id")
        if init.status_code == 200:
            h = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if session:
                h["mcp-session-id"] = session
            await http.post(
                MCP, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            listed = await http.post(
                MCP, headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            )
            text = listed.text
            for tool in ("should_i_ask", "ask_for_help", "recall_experience", "run_experience"):
                check(f"tool {tool}", tool in text)

        print("\nWHAT A STRANGER READS")
        term = await http.get(f"{API}/")
        check("terminal page current", CURRENT in term.text, "curl api.80085.ai")
        stale = [o for o in OLD if o in term.text]
        check("terminal page has no old copy", not stale, ", ".join(stale))

        for name, url in (("llms.txt", f"{API}/llms.txt"), ("agents.md", f"{API}/agents.md")):
            got = await http.get(url)
            check(f"{name} served", got.status_code == 200 and len(got.text) > 200)

        site = await http.get(SITE)
        check("apex responds", site.status_code == 200)
        check(
            "apex page current",
            CURRENT in site.text,
            "Vercel deploy is behind" if CURRENT not in site.text else "",
        )

    failed = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 62)
    print(f"  {len(results) - len(failed)} of {len(results)} live checks pass")
    if failed:
        print("\n  NOT LIVE / NOT CURRENT:")
        for name in failed:
            print(f"    - {name}")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
