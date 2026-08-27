"""Does the unaided agent get it *wrong*? The claim that survives a benchmark.

`agent.py` measured cost and found 80085 loses: on `csv_to_json` and friends it
costs 3.6x-5.8x more input tokens than letting the agent write the code, and no
reliable speed benefit either way (decision 71). Those tasks are all ones where
the naive implementation is *right* -- an agent writes `csv.DictReader` and it
works the first time, so there is nothing to inherit and a registry is pure
overhead.

This measures the other quadrant. Four questions where the obvious
implementation returns a **plausible wrong answer** rather than crashing:
`csv.Sniffer` answering `'\\r'` for a German export, `2021-12-31` for a last
business day that was the 30th. `correctness.py` already proves the *capability*
gets these right where a naive baseline does not. The open question is whether a
real agent, handed the same fixture and no registry, writes the naive baseline.

    CONTROL   -- an agent, a container, a bash tool, no 80085.
    TREATMENT -- the same agent with the 80085 MCP tools attached.

The metric is **pass rate, not time**. Pass rate is binary and needs few
repeats; `agent.py` showed timing at this variance needs far more than it is
worth (34.4s, 65.6s and 88.7s for one arm on one task).

Both arms are asked the question a user would actually ask. Neither is warned
that there is anything subtle about it -- a hint is the whole answer, and an
agent told "watch out for observed holidays" has been handed the Experience in
the prompt.

    ANTHROPIC_API_KEY=... BOOBS_API_KEY=... uv run python benchmarks/agent_correctness.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.agent import WORK, Workspace, arm  # noqa: E402

FIXTURES = ROOT / "capabilities" / "fixtures"
REPEATS = int(os.environ.get("BENCHMARK_REPEATS", "3"))
RESULTS = ROOT / "benchmarks" / "results-agent-correctness.json"

ANSWER = "answer.json"


def _fixture(capability: str, name: str) -> bytes:
    return (FIXTURES / capability / "inputs" / name).read_bytes()


@dataclass(frozen=True)
class Question:
    """One question with a known right answer and a known plausible wrong one.

    `naive` is not decoration. It is what the obvious implementation returns,
    taken from `correctness.py`'s baselines, and reporting it beside the
    agent's answer is what turns "the agent failed" into "the agent returned
    the specific wrong answer we predicted it would".
    """

    capability: str
    ask: str
    inputs: dict[str, bytes]
    field: str
    truth: Any
    naive: Any
    why: str


QUESTIONS = [
    Question(
        capability="remittance_nwf",
        ask=(
            "input.txt is a remittance advice from the freight carrier Northwind "
            "Freight, in their NWF-REMIT-V3 format. What is the settled total, in "
            f'cents? Write {ANSWER} as {{"settled_total_cents": <integer>}} and '
            "nothing else."
        ),
        inputs={"input.txt": (FIXTURES / "remittance_nwf" / "inputs" / "input.txt").read_bytes()},
        field="settled_total_cents",
        truth=121450,
        naive=11114500,
        why=(
            "Three rules decide this number and not one of them is in the file. "
            "Amounts are in tenths of a cent, a trailing minus is a credit, and an "
            "ST of H is a hold that settles in a later advice. An agent reads four "
            "plain rows, sums them, and is wrong by two orders of magnitude with "
            "nothing anywhere to flag it. This is the control case for knowledge "
            "that is not in the input and not in training -- unlike the four below, "
            "where the answer is recoverable by looking harder."
        ),
    ),
    Question(
        capability="sku_meridian",
        ask=(
            "input.txt is a stock line list from Meridian Industries, in their "
            "MERIDIAN-STOCK-V2 format. How many sellable units of stock does it "
            f'represent? Write {ANSWER} as {{"sellable_units": <integer>}} and '
            "nothing else."
        ),
        inputs={"input.txt": _fixture("sku_meridian", "input.txt")},
        field="sellable_units",
        truth=420,
        naive=70,
        why=(
            "Quantities are in cases of twelve, grade K0 is a reject rather than "
            "stock, and revisions below 05 are obsolete tooling that cannot ship. "
            "A reader sees a quantity column and sums it: 70, well formed, wrong "
            "by a factor of six, and objected to by nothing."
        ),
    ),
    Question(
        capability="apilog_zenith",
        ask=(
            "input.txt is an access log from the Zenith internal API gateway, in "
            "their ZENITH-GW-LOG-V4 format. How many requests genuinely failed? "
            f'Write {ANSWER} as {{"failed_requests": <integer>}} and nothing else.'
        ),
        inputs={"input.txt": _fixture("apilog_zenith", "input.txt")},
        field="failed_requests",
        truth=2,
        naive=4,
        why=(
            "299 is this gateway's 'accepted and queued', which is a success; a "
            "retryable 4xx completed on a later hop and is not a failure; a 5xx "
            "always is. Counting status >= 300 gives 4 -- defensible, plausible, "
            "and wrong in the same direction on every dashboard built from it."
        ),
    ),
    Question(
        capability="part_supersede_orbital",
        ask=(
            "input.txt describes an Orbital Systems part supersession chain and an "
            "order, in their ORBITAL-SUPERSEDE-V1 format. Which part number should "
            f'this order actually ship? Write {ANSWER} as {{"resolved_part": "<part>"}} '
            "and nothing else."
        ),
        inputs={"input.txt": _fixture("part_supersede_orbital", "input.txt")},
        field="resolved_part",
        truth="P-140",
        naive="P-190",
        why=(
            "The chain ends at P-190 and following it to the end is the obvious "
            "reading. P-190 is EU-only and this is a US order, so the right answer "
            "is the last US-valid part before it -- which looks, from the file "
            "alone, like deliberately shipping a superseded part."
        ),
    ),
    Question(
        capability="business_days",
        ask=(
            "input.json holds a holiday list and some queries. Using that holiday "
            "list, what is the last business day of December 2021? Write "
            f'{ANSWER} as {{"date": "YYYY-MM-DD"}} and nothing else.'
        ),
        inputs={"input.json": _fixture("business_days", "input.json")},
        field="date",
        truth="2021-12-30",
        naive="2021-12-31",
        why=(
            "New Year's Day 2022 fell on a Saturday and was observed on Friday the "
            "31st -- a closure in neither the weekend rule nor the holiday list the "
            "caller was handed. Payroll and settlement dates turn on it."
        ),
    ),
    Question(
        capability="csv_dialect_sniff",
        ask=(
            "Determine the delimiter used by input.csv. Write "
            f'{ANSWER} as {{"delimiter": "<the delimiter character>"}} and nothing else.'
        ),
        inputs={"input.csv": _fixture("csv_dialect_sniff", "input.csv")},
        field="delimiter",
        truth=";",
        naive="\r",
        why=(
            "`csv.Sniffer` is what the standard library documents for this, and on "
            "this file it answers the carriage return of the CRLF terminator -- "
            "which `csv.reader` then rejects as a bad delimiter value. The standard "
            "library refuses its own sniffer's answer."
        ),
    ),
    Question(
        capability="date_parse",
        ask=(
            'input.json holds a list of date strings. For the value "03/04/2024", '
            "is the date it refers to ambiguous? Write "
            f'{ANSWER} as {{"ambiguous": true}} or {{"ambiguous": false}} and nothing else.'
        ),
        inputs={"input.json": _fixture("date_parse", "input.json")},
        field="ambiguous",
        truth=True,
        naive=False,
        why=(
            "03/04/2024 is the 3rd of April in most of the world and the 4th of "
            "March in the United States. Every date library picks one by default "
            "and never says so, and the answer is a valid date, so nothing "
            "downstream ever complains."
        ),
    ),
    Question(
        capability="encoding_detect",
        ask=(
            "Determine the character encoding of input.txt. Is the whole file in a "
            f"single encoding? Write {ANSWER} as "
            '{"encoding": "<name>", "single_encoding": true|false} and nothing else.'
        ),
        inputs={"input.txt": _fixture("encoding_detect", "input.txt")},
        field="single_encoding",
        truth=False,
        naive=True,
        why=(
            "One line is genuine multi-byte UTF-8 and another does not decode as "
            "UTF-8 at all, so no single answer is right for this file. The "
            "recommended two-liner falls back to latin-1, which cannot fail -- "
            "every byte is a valid code point -- so it always 'succeeds' and turns "
            "Zoe into ZoA« with no error anywhere."
        ),
    ),
]


PROMPT = """You are working in a Linux container. Your working directory is {work}.

{ask}

These files are staged in {work}: {inputs}

There is no network access from your shell and no packages can be installed --
the Python standard library is all there is. Stop once the file is written."""


def _read(workspace: Workspace) -> Any:
    """Whatever the agent wrote, or None if it wrote nothing readable."""
    import subprocess

    done = subprocess.run(
        ["docker", "exec", workspace.name, "cat", f"{WORK}/{ANSWER}"],
        capture_output=True,
    )
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def judge(question: Question):  # type: ignore[no-untyped-def]
    """The harness's own verdict: does the answer match the known truth?

    Deliberately not "did it produce well-formed output". Every arm of
    `agent.py` produced well-formed output and that is exactly why cost was the
    only thing it could measure. Here a confidently wrong answer is the failure
    mode under test, so the only question is whether the value is right.
    """

    async def check(workspace: Workspace) -> bool:
        answer = _read(workspace)
        return isinstance(answer, dict) and answer.get(question.field) == question.truth

    return check


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    key = os.environ.get("BOOBS_API_KEY")
    if not key:
        print(
            "BOOBS_API_KEY is not set. Use a key from an organization already named\n"
            "in EVIDENCE_FIRST_PARTY_ORGANIZATIONS -- measuring the product must not\n"
            "quietly corroborate it (decision 70).",
            file=sys.stderr,
        )
        return 2

    # BENCHMARK_ONLY=a,b re-runs a subset. The four derivable questions have
    # scored 3/3 on both arms every time they have been asked; re-asking them to
    # measure something else is 24 agent runs spent confirming a settled result.
    only = {n.strip() for n in os.environ.get("BENCHMARK_ONLY", "").split(",") if n.strip()}
    questions = [q for q in QUESTIONS if not only or q.capability in only]

    rows: list[dict[str, Any]] = []
    for question in questions:
        prompt = PROMPT.format(work=WORK, ask=question.ask, inputs=", ".join(question.inputs))
        row: dict[str, Any] = {"capability": question.capability, "why": question.why}
        for arm_name, flag in (("control", False), ("treatment", True)):
            passes = 0
            answers: list[Any] = []
            for repeat in range(REPEATS):
                print(f"  {question.capability} {arm_name} {repeat + 1}/{REPEATS}", file=sys.stderr)
                got = await arm(
                    question.capability,
                    prompt,
                    question.inputs,
                    judge(question),
                    with_80085=flag,
                    key=key,
                )
                passes += 1 if got["verified"] else 0
                answers.append(got)
            row[arm_name] = {"passed": passes, "of": REPEATS}
        rows.append(row)

    RESULTS.write_text(json.dumps(rows, indent=2) + "\n")

    header = f"{'capability':<20}{'control':>12}{'treatment':>12}   the wrong answer"
    print(f"\n{header}\n{'-' * len(header)}")
    for row, question in zip(rows, questions, strict=True):
        print(
            f"{row['capability']:<20}"
            f"{row['control']['passed']}/{row['control']['of']:<10}"
            f"{row['treatment']['passed']}/{row['treatment']['of']:<10}"
            f"   {question.naive!r} (right: {question.truth!r})"
        )
    print(f"\nmodel via agent.py, {REPEATS} repeats. Written to {RESULTS.name}.")
    print(
        "\nPass rate, not time. A control arm that scores 0 is not a slow agent --\n"
        "it is an agent returning a plausible wrong answer that nothing downstream\n"
        "would ever flag."
    )
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
