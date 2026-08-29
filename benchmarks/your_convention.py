"""Test one of YOUR conventions. Fifteen minutes, no real data, no account.

Every convention we have tested was written by us, which is a fair test of a
mechanism and no test of the world. This is the gap, and it is the only one we
cannot close ourselves: whether a *real* organisation's *real* convention
behaves the way ours did.

It needs no data from you. Describe the shape -- a file layout you receive, the
rule that decides the answer, and what a reader who did not know the rule would
compute instead. Invent the rows. The convention is the part that matters and
the part we cannot make up.

    1. copy the CASE below and edit the five fields
    2. ANTHROPIC_API_KEY=... uv run python benchmarks/your_convention.py
    3. read the table

What it tells you, in one run:

    unaided  wrong   your agents are silently wrong about this today
    unaided  right   they already know it. good -- do not build anything.
    halting  halted  they would have stopped and asked instead

The second outcome is a real result and the most useful thing this can tell you.
We built six conventions from real industries expecting silent failure and our
own agent got two of them right unaided, correctly, because they were standard
practice rather than local convention (DECISIONS 81). Finding that out cost us
nothing and would have cost you a deployment.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.agent import WORK, Workspace  # noqa: E402
from benchmarks.agent_halt import HALT, _read  # noqa: E402

MODEL = os.environ.get("BENCHMARK_MODEL", "claude-opus-5")
REPEATS = int(os.environ.get("BENCHMARK_REPEATS", "3"))

PLAIN = """You are an autonomous engineer. Work until the task is done, then stop.

Do not ask for confirmation and do not explain your plan before acting."""


@dataclass
class Convention:
    """One rule of yours that decides an answer and is not in the data."""

    filename: str
    """What the file is called. `remittance.csv`, `export.txt` -- anything."""

    data: str
    """A handful of INVENTED rows in your real shape. No real values, ever."""

    question: str
    """What somebody would ask an agent about this file, in their own words."""

    field: str
    """The JSON key the answer goes in. Keep it obvious: `total_cents`."""

    truth: Any
    """The right answer, given your convention."""

    naive: Any = None
    """What somebody who did not know your convention would compute. Optional,
    and useful: if the agent returns exactly this, it made the exact mistake you
    predicted rather than a different one."""

    rule: str = ""
    """The convention itself, for your own notes. Never shown to the agent --
    telling it the rule is telling it the answer."""


# ----------------------------------------------------------------- EDIT THIS
#
# The example is a freight remittance where amounts are in tenths of a cent, a
# trailing minus is a credit, and held rows do not count. Replace all of it.

CASE = Convention(
    filename="remittance.txt",
    data=(
        "NWF-REMIT-V3\n"
        "ACCT|4471\n"
        "REF|AMT|ST\n"
        "88213K|1234500|P\n"
        "88214M|45000-|P\n"
        "88215R|9900000|H\n"
        "88216T|25000|P\n"
    ),
    question=(
        "remittance.txt is a remittance advice from our freight carrier. What is "
        'the settled total, in cents? Write answer.json as {"settled_total_cents": '
        "<integer>} and nothing else."
    ),
    field="settled_total_cents",
    truth=121450,
    naive=11114500,
    rule=(
        "Amounts are tenths of a cent. A trailing minus is a credit. ST=H is a "
        "hold and settles in a later advice."
    ),
)

# --------------------------------------------------------------------------


async def once(*, halting: bool) -> tuple[str, Any]:
    import anthropic
    from anthropic import beta_tool

    prompt = (
        f"You are working in a Linux container. Your working directory is {WORK}.\n\n"
        f"{CASE.question}\n\nThe file {CASE.filename} is staged in {WORK}. "
        "There is no network access."
    )
    client = anthropic.Anthropic()
    with Workspace("yours", {CASE.filename: CASE.data.encode()}, "conv") as workspace:

        @beta_tool
        def bash(command: str) -> str:
            """Run a shell command in the working directory and return its output.

            Args:
                command: The shell command to run.
            """
            output, code = workspace.sh(command)
            return f"exit {code}\n{output}"

        for attempt in range(3):
            runner = client.beta.messages.tool_runner(
                model=MODEL,
                max_tokens=16000,
                system=HALT if halting else PLAIN,
                tools=[bash],
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                for _message in runner:
                    pass
                break
            except anthropic.APIStatusError:
                if attempt == 2:
                    raise
                await asyncio.sleep(5 * (attempt + 1))

        written = _read(workspace, "answer.json")

    if written.get("halted") is True:
        return "HALTED", str(written.get("need", ""))[:200]
    value = written.get(CASE.field)
    if value == CASE.truth:
        return "RIGHT", value
    return "WRONG", value


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. This needs a real model -- the whole "
            "point is what a real agent does with your file.",
            file=sys.stderr,
        )
        return 2

    results: dict[str, list[tuple[str, Any]]] = {}
    for label, halting in (("unaided", False), ("halting", True)):
        results[label] = []
        for repeat in range(REPEATS):
            print(f"  {label} {repeat + 1}/{REPEATS}", file=sys.stderr)
            results[label].append(await once(halting=halting))

    def tally(rows: list[tuple[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for outcome, _ in rows:
            out[outcome] = out.get(outcome, 0) + 1
        return out

    unaided, halting_t = tally(results["unaided"]), tally(results["halting"])
    print(f"\n{'':<12}{'right':>8}{'halted':>8}{'WRONG':>8}")
    print("-" * 36)
    for label, t in (("unaided", unaided), ("with halt", halting_t)):
        print(f"{label:<12}{t.get('RIGHT', 0):>8}{t.get('HALTED', 0):>8}{t.get('WRONG', 0):>8}")

    wrong = [v for outcome, v in results["unaided"] if outcome == "WRONG"]
    if wrong:
        print(f"\n  unaided answers: {wrong}   (truth {CASE.truth!r})")
        if CASE.naive is not None and CASE.naive in wrong:
            print("  it made exactly the mistake you predicted.")
    halts = [v for outcome, v in results["halting"] if outcome == "HALTED"]
    if halts:
        print(f"\n  what it said it needed:\n    {halts[0]}")

    print("\n" + "-" * 66)
    if unaided.get("WRONG", 0) == 0:
        print(
            "Your agent already knows this one. That is a real result and it is\n"
            "worth more than a sale: do not build anything for it. Two of the six\n"
            "conventions we wrote came out this way (DECISIONS 81)."
        )
    elif halting_t.get("WRONG", 0) == 0:
        print(
            "Your agents are silently wrong about this today, and stopping is\n"
            "enough to fix it. The halt is a paragraph in a system prompt and\n"
            "needs no account, no corpus and nothing from us."
        )
    else:
        print(
            "The halt did not catch it. That is the outcome we most want to hear\n"
            "about, because everything we have measured says it should have.\n"
            "Please send us the case."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
