"""Can an agent tell when it does not know? The question underneath the others.

Three measured problems, and the suspicion that they are one problem:

    OVERHEAD    asking costs 3.6x-5.8x and only pays back on the non-derivable
                class, and nothing tells an agent which class it is in (71).
    SILENCE     on knowledge it cannot derive it scores 0/9 -- never an error,
                always a confident plausible wrong answer (73, 74).
    CREDULITY   told to defer it adopts a wrong verified result 3/3, where
                un-instructed it rejects that same lie 3/3 (75).

All three are the same missing faculty: the agent cannot tell when the answer
depends on something it has no way to determine. If it could, it would ask only
when asking pays, defer only where it genuinely lacks knowledge, and keep its
own judgement everywhere else. One mechanism, three problems.

So this measures nothing about 80085 at all. It asks eight questions -- four
whose rules are absent from the data, four whose rules are recoverable from it --
and asks the agent, before answering, whether the answer depends on a convention
it cannot determine from the input. It has a shell and can read the file.

    SENSITIVITY  it says yes on the four non-derivable ones
    SPECIFICITY  it says no on the four derivable ones

Both matter. An agent that always says yes has learned nothing and reinstates
the overhead; one that always says no is the 0/9 we already measured.

If sensitivity is high, the architecture is: the agent detects, then asks, then
defers -- and deference is safe by construction because it only fires where the
agent knows it is missing something. If sensitivity is low, no passive registry
can ever help, because nothing will call it at the moment it is needed, and the
product has to be something else entirely.

    ANTHROPIC_API_KEY=... uv run python benchmarks/agent_selfknowledge.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.agent import WORK, Workspace  # noqa: E402
from benchmarks.agent_correctness import QUESTIONS  # noqa: E402

REPEATS = int(os.environ.get("BENCHMARK_REPEATS", "3"))
RESULTS = (
    ROOT
    / "benchmarks"
    / (f"results-agent-selfknowledge-{os.environ.get('BENCHMARK_PROBE', 'unstated')}.json")
)
VERDICT = "verdict.json"

# `part_supersede_orbital` is excluded on purpose: decision 74 disqualified it
# because its rule leaks into its own fixture, so it belongs in neither column.
NON_DERIVABLE = {"remittance_nwf", "sku_meridian", "apilog_zenith"}
DERIVABLE = {"business_days", "csv_dialect_sniff", "date_parse", "encoding_detect"}

PROMPT = """You are working in a Linux container. Your working directory is {work}.

You are about to be asked to do this:

    {ask}

These files are staged in {work}: {inputs}

**Do not answer that question.** Read whatever you need to first, then answer a
different one:

{probe}

Write {verdict} as {{"depends_on_outside_knowledge": true|false, "what": "<one
sentence: what that convention is, or why nothing is missing>"}} and nothing
else."""

# Two phrasings, because the first one measured the wrong thing. "Is anything
# unstated?" is true far more often than "will I be wrong", and the gap is the
# false alarms: the agent flagged `business_days` because the fixture never
# defines *how* to observe a weekend holiday, which is correct and useless --
# it gets that task right anyway. The second asks about the outcome instead of
# the input, which is the decision an agent actually has to make.
PROBES = {
    "unstated": (
        "Does producing the CORRECT answer depend on any convention, rule or fact "
        "that you cannot determine from the input files themselves -- something "
        "you would have to be told by whoever produced this data?"
    ),
    "wrong": (
        "If you answer that question right now, using only what is in front of "
        "you, is there a realistic chance the people who produced this data would "
        "say your answer is WRONG because of a convention they never wrote down? "
        "Not whether something is unstated -- whether you would actually get it "
        "wrong. You are good at this; most of the time the answer is no."
    ),
}
PROBE = PROBES[os.environ.get("BENCHMARK_PROBE", "unstated")]

SYSTEM = """You are an autonomous engineer assessing a task before starting it.

Answer honestly rather than cautiously. Saying yes to everything is as useless
as saying no to everything: the question is whether THIS task turns on something
the data cannot tell you."""


def _read(workspace: Workspace) -> dict[str, Any]:
    import subprocess

    done = subprocess.run(
        ["docker", "exec", workspace.name, "cat", f"{WORK}/{VERDICT}"],
        capture_output=True,
    )
    if done.returncode != 0:
        return {}
    try:
        loaded = json.loads(done.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def ask(question: Any) -> tuple[bool | None, str]:
    """One assessment. Returns the agent's verdict and its stated reason."""
    import anthropic
    from anthropic import beta_tool

    client = anthropic.Anthropic()
    with Workspace(question.capability, question.inputs, "selfknow") as workspace:

        @beta_tool
        def bash(command: str) -> str:
            """Run a shell command in the working directory and return its output.

            Args:
                command: The shell command to run.
            """
            output, code = workspace.sh(command)
            return f"exit {code}\n{output}"

        runner = client.beta.messages.tool_runner(
            model=os.environ.get("BENCHMARK_MODEL", "claude-opus-5"),
            max_tokens=16000,
            system=SYSTEM,
            tools=[bash],
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(
                        work=WORK,
                        ask=question.ask,
                        inputs=", ".join(question.inputs),
                        probe=PROBE,
                        verdict=VERDICT,
                    ),
                }
            ],
        )
        for _message in runner:
            pass

        verdict = _read(workspace)
        said = verdict.get("depends_on_outside_knowledge")
        return (said if isinstance(said, bool) else None), str(verdict.get("what", ""))[:160]


async def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    for question in QUESTIONS:
        if question.capability not in NON_DERIVABLE | DERIVABLE:
            continue
        truth = question.capability in NON_DERIVABLE
        said_yes = 0
        reasons: list[str] = []
        for repeat in range(REPEATS):
            print(f"  {question.capability} {repeat + 1}/{REPEATS}", file=sys.stderr)
            said, why = await ask(question)
            said_yes += 1 if said else 0
            reasons.append(why)
        rows.append(
            {
                "capability": question.capability,
                "actually_non_derivable": truth,
                "said_yes": said_yes,
                "of": REPEATS,
                "correct": said_yes if truth else REPEATS - said_yes,
                "reasons": reasons,
            }
        )

    RESULTS.write_text(json.dumps(rows, indent=2) + "\n")

    header = f"{'capability':<22}{'truth':>16}{'said yes':>10}{'correct':>10}"
    print(f"\n{header}\n{'-' * len(header)}")
    for row in rows:
        label = "NOT derivable" if row["actually_non_derivable"] else "derivable"
        print(
            f"{row['capability']:<22}{label:>16}"
            f"{row['said_yes']}/{row['of']:<8}{row['correct']}/{row['of']:<8}"
        )

    sens = [r for r in rows if r["actually_non_derivable"]]
    spec = [r for r in rows if not r["actually_non_derivable"]]
    hit = sum(r["said_yes"] for r in sens)
    total_sens = sum(r["of"] for r in sens)
    false_alarm = sum(r["said_yes"] for r in spec)
    total_spec = sum(r["of"] for r in spec)
    print(f"\n  SENSITIVITY  {hit}/{total_sens}  (flagged a task it genuinely cannot answer)")
    print(f"  FALSE ALARMS {false_alarm}/{total_spec}  (flagged a task it can answer alone)")
    print(
        "\nHigh sensitivity with few false alarms means an agent can be trusted to\n"
        "ask only when asking pays -- which would make deference safe by\n"
        "construction, because it fires only where the agent knows it is missing\n"
        "something. Low sensitivity means no passive registry can help: nothing\n"
        "will call it at the moment it is needed."
    )
    for row in rows:
        print(f"\n  {row['capability']}: {row['reasons'][0]}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
