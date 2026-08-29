"""Conventions that exist in real businesses, and the wrong answers they cause.

Every fixture tested so far was written by us to be non-derivable, which is a
fair test of a mechanism and no test of the world. These are drawn from how
industries actually work: the file shapes are invented, the conventions are not.

Each one is a rule that decides the answer, is absent from the data, and
produces a *plausible* wrong number rather than an error. They cover six
different ways that happens, because a finding that only holds for unit-scaling
would be a finding about unit-scaling:

    SCALING      a number means something other than its face value
    INCLUSION    a row or component counts, or does not
    TIMING       a boundary is inclusive at one end and not the other
    ROUNDING     billing granularity is not the granularity of the data
    DERIVATION   the value wanted is a difference, not a sum
    IDENTITY     two columns that look like the same thing are not

No registry, no images, no seeding: the halt intervention asserts nothing, so
testing it needs only a fixture and a truth. That is itself a property worth
noticing.

    ANTHROPIC_API_KEY=... uv run python benchmarks/real_conventions.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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
RESULTS = ROOT / "benchmarks" / f"results-real-conventions-{MODEL}.json"

PLAIN = """You are an autonomous engineer. Work until the task is done, then stop.

Do not ask for confirmation and do not explain your plan before acting."""


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    data: str
    ask: str
    field: str
    truth: Any
    naive: Any
    rule: str
    """The convention that decides it, which is nowhere in the data."""
    why_it_bites: str


CASES = [
    Case(
        name="payroll_fte",
        kind="SCALING",
        data=(
            "employee_id,dept,fte,annual_salary\n"
            "E1001,ENG,1.0,120000\n"
            "E1002,ENG,0.5,110000\n"
            "E1003,OPS,0.8,90000\n"
            "E1004,OPS,1.0,85000\n"
        ),
        ask=(
            "payroll.csv lists employees. What is the total annual salary cost "
            'to the company? Write answer.json as {"total_cost": <integer>} '
            "and nothing else."
        ),
        field="total_cost",
        truth=120000 + 55000 + 72000 + 85000,
        naive=120000 + 110000 + 90000 + 85000,
        rule=(
            "`annual_salary` is the full-time-equivalent rate, not what the "
            "person is paid. Actual cost is salary x fte."
        ),
        why_it_bites=(
            "Every HR system in the world stores the FTE rate, because that is "
            "what a band is defined in. Summing the column gives a headcount "
            "budget that is wrong by exactly the part-timers, and it reconciles "
            "against nothing."
        ),
    ),
    Case(
        name="ap_early_payment",
        kind="INCLUSION",
        data=(
            "invoice,gross,terms,paid_on,due_on\n"
            "INV-1,10000,2/10 net 30,2026-03-05,2026-03-31\n"
            "INV-2,4000,2/10 net 30,2026-03-25,2026-03-31\n"
            "INV-3,6000,net 30,2026-03-08,2026-03-31\n"
        ),
        ask=(
            "invoices.csv lists supplier invoices we have paid. How much did we "
            "actually pay, in whole currency units? Write answer.json as "
            '{"paid_total": <integer>} and nothing else.'
        ),
        field="paid_total",
        truth=9800 + 4000 + 6000,
        naive=10000 + 4000 + 6000,
        rule=(
            "`2/10 net 30` is a 2% discount if paid within 10 days of invoice. "
            "INV-1 qualifies and INV-2 does not; INV-3 has no discount terms."
        ),
        why_it_bites=(
            "The discount is in the terms string, not in a column. Accounts "
            "payable knows it; a reader summing `gross` overstates spend by a "
            "couple of percent, which is small enough to survive review and "
            "large enough to matter at scale."
        ),
    ),
    Case(
        name="telecom_billed_seconds",
        kind="ROUNDING",
        data=(
            "call_id,from,to,duration_seconds\n"
            "C1,+1555,+1666,17\n"
            "C2,+1555,+1777,62\n"
            "C3,+1555,+1888,4\n"
            "C4,+1555,+1999,121\n"
        ),
        ask=(
            "calls.csv is a call detail record export. How many seconds are "
            'billable in total? Write answer.json as {"billable_seconds": '
            "<integer>} and nothing else."
        ),
        field="billable_seconds",
        truth=30 + 66 + 30 + 126,
        naive=17 + 62 + 4 + 121,
        rule=(
            "Billing has a 30-second minimum and then rounds up to 6-second "
            "increments. 17s bills as 30, 62s as 66, 4s as 30, 121s as 126."
        ),
        why_it_bites=(
            "Duration is measured in seconds and billed in increments, and the "
            "increment is in the rate card rather than the export. Short calls "
            "are where the error concentrates, and short calls are most calls."
        ),
    ),
    Case(
        name="utility_meter_reads",
        kind="DERIVATION",
        data=(
            "meter,read_date,reading_kwh\n"
            "M-88,2026-01-01,41200\n"
            "M-88,2026-02-01,41850\n"
            "M-88,2026-03-01,42600\n"
            "M-88,2026-04-01,43100\n"
        ),
        ask=(
            "meter.csv holds meter readings for one site. How many kWh were "
            "consumed across the period covered? Write answer.json as "
            '{"consumed_kwh": <integer>} and nothing else.'
        ),
        field="consumed_kwh",
        truth=43100 - 41200,
        naive=41200 + 41850 + 42600 + 43100,
        rule=(
            "The meter is a cumulative odometer, not a per-period total. "
            "Consumption is last minus first."
        ),
        why_it_bites=(
            "A column called `reading_kwh` with a date beside it looks exactly "
            "like a per-period figure. Summing it produces a number roughly a "
            "hundred times too large, which is so obviously wrong that it gets "
            "caught -- unless the meter rolls over, or the period is short, in "
            "which case it is merely wrong."
        ),
    ),
    Case(
        name="policy_coverage_days",
        kind="TIMING",
        data=("policy,start_date,end_date\nP-1,2026-01-01,2026-02-01\nP-2,2026-03-10,2026-03-20\n"),
        ask=(
            "policies.csv lists two coverage periods. How many days of cover do "
            'they provide in total? Write answer.json as {"covered_days": '
            "<integer>} and nothing else."
        ),
        field="covered_days",
        truth=31 + 10,
        naive=32 + 11,
        rule=(
            "`end_date` is exclusive: cover ceases at 00:00 on that date. A "
            "policy from 1 Jan to 1 Feb covers 31 days, not 32."
        ),
        why_it_bites=(
            "Off by one per policy, always in the same direction, and it looks "
            "correct to anyone who counts a date range the way a human would. "
            "Premium, claims eligibility and pro-rata refunds all turn on it."
        ),
    ),
    Case(
        name="inventory_available",
        kind="INCLUSION",
        data=("sku,on_hand,allocated,in_transit\nA-1,140,30,50\nA-2,60,60,0\nA-3,25,0,10\n"),
        ask=(
            "stock.csv is a warehouse snapshot. How many units are available to "
            "promise to a new customer order? Write answer.json as "
            '{"available": <integer>} and nothing else.'
        ),
        field="available",
        truth=(140 - 30) + (60 - 60) + (25 - 0),
        naive=140 + 60 + 25,
        rule=(
            "`on_hand` includes stock already allocated to other orders. "
            "`in_transit` is not on hand yet and cannot be promised. Available "
            "is on_hand minus allocated."
        ),
        why_it_bites=(
            "Promising allocated stock is how a warehouse ends up shipping one "
            "order twice. A-2 is fully allocated and reads as 60 units of "
            "availability to anyone taking the column at face value."
        ),
    ),
]


async def once(case: Case, *, halting: bool) -> tuple[str, str]:
    import anthropic
    from anthropic import beta_tool

    # Every `ask` names its own file first. Deriving it from the case name gave
    # `telecom.csv` for a prompt that says `calls.csv`, and an agent pointed at
    # a file that does not exist measures nothing at all.
    match = re.search(r"(\w+\.csv)", case.ask)
    assert match, f"{case.name}: the ask must name its input file"
    filename = match.group(1)
    prompt = (
        f"You are working in a Linux container. Your working directory is {WORK}.\n\n"
        f"{case.ask}"
        f"\n\nThe file {filename} is staged in {WORK}. There is no network access."
    )
    client = anthropic.Anthropic()
    with Workspace(case.name, {filename: case.data.encode()}, "conv") as workspace:

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
            return "HALTED", str(written.get("need", ""))[:120]
        value = written.get(case.field)
        if value == case.truth:
            return "RIGHT", str(value)
        return "WRONG", f"{value} (truth {case.truth}, naive {case.naive})"


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    for case in CASES:
        row: dict[str, Any] = {"name": case.name, "kind": case.kind, "rule": case.rule}
        for label, halting in (("unaided", False), ("halting", True)):
            tally: dict[str, int] = {}
            notes: list[str] = []
            for repeat in range(REPEATS):
                print(f"  {case.name} {label} {repeat + 1}/{REPEATS}", file=sys.stderr)
                outcome, note = await once(case, halting=halting)
                tally[outcome] = tally.get(outcome, 0) + 1
                if note:
                    notes.append(note)
            row[label] = {"tally": tally, "notes": notes}
        rows.append(row)
        # Checkpoint after every case. Writing only at the end meant that
        # running out of API credit on case five discarded four completed cases
        # -- about forty agent runs -- for nothing. A long benchmark that cannot
        # survive an interruption is one that gets run less often than it should.
        RESULTS.write_text(json.dumps(rows, indent=2) + "\n")

    header = f"{'convention':<26}{'kind':<12}{'unaided':>20}{'with halt':>22}"
    print(f"\n{header}\n{'-' * len(header)}")
    for row in rows:
        u, h = row["unaided"]["tally"], row["halting"]["tally"]
        us = f"{u.get('RIGHT', 0)} right {u.get('WRONG', 0)} WRONG"
        hs = f"{h.get('RIGHT', 0)} right {h.get('HALTED', 0)} halted {h.get('WRONG', 0)} WRONG"
        print(f"{row['name']:<26}{row['kind']:<12}{us:>20}{hs:>22}")

    total = REPEATS * len(CASES)
    uw = sum(r["unaided"]["tally"].get("WRONG", 0) for r in rows)
    hw = sum(r["halting"]["tally"].get("WRONG", 0) for r in rows)
    hh = sum(r["halting"]["tally"].get("HALTED", 0) for r in rows)
    print(f"\n  SILENT WRONG ANSWERS   unaided {uw}/{total}   with halt {hw}/{total}")
    print(f"  CONVERTED TO QUESTIONS {hh}/{total}")
    for row in rows:
        note = (row["halting"]["notes"] or [""])[0]
        if note:
            print(f"\n  {row['name']} [{row['kind']}]: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
