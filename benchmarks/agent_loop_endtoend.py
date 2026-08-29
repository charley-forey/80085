"""The whole product, with real agents, once.

Everything else in this directory measures one property. This checks that the
thing actually works when a real model drives it, because every part of the loop
has been tested and the loop itself never has:

    agent one   halts, asks for help, gets nothing, and stops
    a human     answers it, in a sentence
    agent two   asks the same thing in its own words -- and does not stop

If that fails, the API is correct and the product does not exist. `curl` proving
each endpoint is not the same claim.

Deliberately not mocked. Real model, real MCP tool surface, real question rows.
The only shortcut is that the tools are local functions calling the live API
rather than the hosted MCP endpoint, so this can run against a local stack.

    ANTHROPIC_API_KEY=... BOOBS_API_KEY=... uv run python benchmarks/agent_loop_endtoend.py
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
sys.path.insert(0, str(ROOT))

from benchmarks.agent import WORK, Workspace  # noqa: E402
from benchmarks.agent_halt import HALT  # noqa: E402

MODEL = os.environ.get("BENCHMARK_MODEL", "claude-opus-5")
API = os.environ.get("BOOBS_API_URL", "https://api.80085.ai")

# The Zenith log again: the truth is 2, naive readings give 3 or 4, and the rule
# that decides it is nowhere in the file.
LOG = "1|/orders|200|0\n2|/orders|299|0\n3|/ship|429|1\n4|/ship|400|0\n5|/pay|503|1\n6|/pay|299|0\n"
ASK = (
    "input.txt is an access log from our internal API gateway. How many "
    'requests genuinely failed? Write answer.json as {"failed_requests": '
    "<integer>} and nothing else."
)
TRUTH = 2

SYSTEM = (
    HALT
    + """

You have a tool called ask_for_help. If you find you are missing a convention
you cannot determine, call it BEFORE you halt: somebody may already have
answered it, in which case you can simply carry on."""
)


async def run_agent(key: str, label: str) -> dict[str, Any]:
    """One agent, one attempt, with the real tool surface."""
    import anthropic
    from anthropic import beta_tool

    client = anthropic.Anthropic()
    seen: dict[str, Any] = {"asked_for_help": False, "was_answered": None}

    with Workspace("loop", {"input.txt": LOG.encode()}, label) as workspace:

        @beta_tool
        def bash(command: str) -> str:
            """Run a shell command in the working directory and return its output.

            Args:
                command: The shell command to run.
            """
            output, code = workspace.sh(command)
            return f"exit {code}\n{output}"

        @beta_tool
        def ask_for_help(need: str) -> str:
            """You are missing something you cannot work out. Say so here rather than guessing.

            Say what you would have to be TOLD, not what you are trying to do.

            Args:
                need: The specific convention you would have to be told.
            """
            seen["asked_for_help"] = True
            seen["need"] = need
            posted = httpx.post(
                f"{API}/v1/questions",
                headers={"Authorization": f"Bearer {key}"},
                json={"need": need},
                timeout=60,
            ).json()
            answer = posted.get("answer")
            seen["question_id"] = posted.get("question_id")
            seen["was_answered"] = bool(answer)
            if answer:
                return json.dumps({"answered": True, "answer": answer["body"]})
            return json.dumps(
                {
                    "answered": False,
                    "what_to_do": "Nobody has answered this. Stop and say what you are missing.",
                }
            )

        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=[bash, ask_for_help],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are working in a Linux container. Your working directory "
                        f"is {WORK}.\n\n{ASK}\n\nThe file input.txt is staged there."
                    ),
                }
            ],
        )
        for _message in runner:
            pass

        text = workspace.sh(f"cat {WORK}/answer.json")[0]
        body = text.split("\n", 1)[1] if text.startswith("exit") else text
        try:
            written = json.loads(body)
        except Exception:
            written = {}

    seen["halted"] = written.get("halted") is True
    seen["answer"] = written.get("failed_requests")
    seen["correct"] = written.get("failed_requests") == TRUTH
    return seen


async def main() -> int:
    key = os.environ.get("BOOBS_API_KEY")
    if not (os.environ.get("ANTHROPIC_API_KEY") and key):
        print("ANTHROPIC_API_KEY and BOOBS_API_KEY are both required.", file=sys.stderr)
        return 2

    print("1. an agent hits a convention it cannot know", file=sys.stderr)
    first = await run_agent(key, "first")

    print("2. a human answers it, once", file=sys.stderr)
    async with httpx.AsyncClient(timeout=60) as http:
        answered = await http.post(
            f"{API}/v1/questions/{first['question_id']}/answer",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "body": (
                    "299 is 'accepted and queued' and counts as a success. A 4xx with the "
                    "retry flag set completed on a later hop and is not a failure. "
                    "A 5xx always is."
                ),
                "answered_by": "sam",
            },
        )

    print("3. a second agent asks the same thing in its own words", file=sys.stderr)
    second = await run_agent(key, "second")

    print("\n" + "=" * 66)
    print(f"{'':<26}{'first agent':>18}{'second agent':>20}")
    print("-" * 66)
    print(f"{'asked for help':<26}{first['asked_for_help']!s:>18}{second['asked_for_help']!s:>20}")
    print(f"{'got an answer back':<26}{first['was_answered']!s:>18}{second['was_answered']!s:>20}")
    print(f"{'halted':<26}{first['halted']!s:>18}{second['halted']!s:>20}")
    print(f"{'wrote an answer':<26}{str(first['answer']):>18}{str(second['answer']):>20}")
    print(f"{'and it was right':<26}{first['correct']!s:>18}{second['correct']!s:>20}")
    print("=" * 66)
    print(f"\nhuman answered: HTTP {answered.status_code}")
    print(f"first agent asked for: {first.get('need', '')[:120]}")
    print(f"second agent asked for: {second.get('need', '')[:120]}")

    ok = (
        first["asked_for_help"]
        and not first["was_answered"]
        and not first["correct"]
        and second["was_answered"]
        and second["correct"]
    )
    print(
        "\nLOOP CLOSED: the second agent did not have to stop."
        if ok
        else "\nLOOP DID NOT CLOSE. The API is correct and the product is not."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
