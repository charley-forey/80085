"""What a fresh implementation gets wrong.

`run.py` measures time to a verified result, and it is honest that the number
is near parity: its control arm rebuilds an example that is *already correct*,
so it compares a docker build against a container pull. That is a fair floor
and a useless ceiling -- and it is exactly as easy for `mojibake_repair` as for
`csv_to_json`, which is why adding the hard capabilities to it would only
inflate a number that measures nothing.

For a capability whose value is accumulated edge cases, the interesting claim
is not "faster than rebuilding". It is:

    correct where a fresh implementation is subtly wrong

So this benchmark does not time anything. It runs the real capability and a
*naive baseline* -- the obvious ten-minute implementation a competent engineer
or agent writes first -- over the same adversarial input, and reports where
they disagree.

The baselines below are not strawmen. Each is what the standard library's own
documentation nudges you toward, and each is wrong in a way that produces a
plausible answer rather than an error. That is the whole point: a crash gets
fixed, a plausible wrong answer gets shipped and believed.

    uv run python benchmarks/correctness.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "capabilities" / "examples"
FIXTURES = ROOT / "capabilities" / "fixtures"


# --------------------------------------------------------------- the baselines


def naive_date_parse(payload: dict[str, Any]) -> dict[str, Any]:
    """One format, one answer. What every date library does by default.

    `03/04/2024` is the 3rd of April in most of the world and the 4th of March
    in the United States. This picks one and never says so.
    """
    from datetime import datetime

    out = []
    for value in payload["values"]:
        parsed = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d %b %Y"):
            try:
                parsed = datetime.strptime(value, fmt).date().isoformat()
                break
            except ValueError:
                continue
        out.append({"input": value, "iso": parsed, "ambiguous": False})
    return {"values": out}


def naive_encoding_detect(raw: bytes) -> dict[str, Any]:
    """Try UTF-8, fall back to latin-1. The universally recommended two-liner.

    It assumes the file has *an* encoding. latin-1 cannot fail -- every byte
    is a valid code point -- so the fallback always "succeeds", which is
    exactly what makes it dangerous.
    """
    try:
        raw.decode("utf-8")
        return {"encoding": "utf-8", "ambiguous": False, "mixed": False}
    except UnicodeDecodeError:
        return {"encoding": "latin-1", "ambiguous": False, "mixed": False}


def naive_last_business_day(year: int, month: int, holidays: set[str]) -> str:
    """Walk back from month end past weekends and the holiday list.

    Which is the rule everyone knows, and half the rule. A public holiday that
    falls at a weekend is *observed* on an adjacent weekday, and that weekday
    is closed even though it is neither a weekend nor in the list you were
    given.
    """
    day = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    while day.weekday() >= 5 or day.isoformat() in holidays:
        day -= timedelta(days=1)
    return day.isoformat()


def naive_csv_dialect(sample: str) -> dict[str, Any]:
    """csv.Sniffer, which the standard library documents for exactly this.

    It is a frequency heuristic over a sample, and it will happily return a
    character that is not a delimiter at all. On this fixture it picks the
    carriage return of the CRLF terminator -- which `csv.reader` then refuses
    as a bad delimiter value, so the standard library rejects its own
    sniffer's answer.
    """
    try:
        return {"delimiter": csv.Sniffer().sniff(sample).delimiter}
    except csv.Error as exc:
        return {"delimiter": None, "error": str(exc)}


# ------------------------------------------------------------------ the cases


@dataclass
class Case:
    capability: str
    what: str
    """The specific thing being got wrong, in one line."""
    naive: Callable[[], Any]
    truth: Callable[[dict[str, Any]], Any]
    """Pulls the real answer out of the capability's own result.json."""
    matters: str
    notes: list[str] = field(default_factory=list)


def _fixture_bytes(capability: str, name: str) -> bytes:
    return (FIXTURES / capability / "inputs" / name).read_bytes()


def _fixture_json(capability: str, name: str) -> dict[str, Any]:
    return dict(json.loads(_fixture_bytes(capability, name).decode("utf-8")))


CASES = [
    Case(
        capability="date_parse",
        what="03/04/2024 -- is it 3 April or 4 March?",
        naive=lambda: naive_date_parse(_fixture_json("date_parse", "input.json"))["values"][0],
        truth=lambda result: next(v for v in result["values"] if v["input"] == "03/04/2024"),
        matters=(
            "The naive answer is a valid date, so nothing downstream ever complains. "
            "A month of reports is wrong and looks fine."
        ),
    ),
    Case(
        capability="encoding_detect",
        what="a CSV whose second line is real UTF-8 and whose third is latin-1",
        naive=lambda: naive_encoding_detect(_fixture_bytes("encoding_detect", "input.txt")),
        truth=lambda result: {
            "encoding": result.get("encoding"),
            "ambiguous": result.get("ambiguous"),
            "mixed": result.get("mixed_encoding"),
        },
        matters=(
            "The file is not in one encoding, so no single answer is right for it. "
            "latin-1 never raises, so the fallback always succeeds -- and decoding "
            'the genuine UTF-8 line that way turns Zoe/Muenchen into "ZoÃ«, MÃ¼nchen" '
            "with no error anywhere. The capability says cp1252 *and* that the "
            "question has no single answer, which is the part you can act on."
        ),
    ),
    Case(
        capability="business_days",
        what="the last business day of December 2021, given the same holiday list",
        naive=lambda: {
            "answer": naive_last_business_day(
                2021, 12, set(_fixture_json("business_days", "input.json")["holidays"])
            )
        },
        truth=lambda result: {
            "answer": next(
                q["date"]
                for q in result["queries"]
                if q.get("kind") == "last_business_day"
                and str(q.get("calendar_last", "")).startswith("2021-12")
            )
        },
        matters=(
            "New Year's Day 2022 fell on a Saturday, so it was observed on Friday "
            "the 31st -- a closure that is in neither the weekend rule nor the "
            "holiday list it was handed. Payroll and settlement dates turn on it."
        ),
    ),
    Case(
        capability="csv_dialect_sniff",
        what="the same German export: BOM, semicolons, an embedded newline, a comma inside quotes",
        naive=lambda: naive_csv_dialect(
            _fixture_bytes("csv_dialect_sniff", "input.csv").decode("utf-8-sig")
        ),
        truth=lambda result: {"delimiter": result.get("delimiter")},
        matters=(
            "Sniffer does not answer ';'. It answers '\\r' -- the carriage return "
            "of the CRLF terminator outscores the real delimiter -- and csv.reader "
            "then rejects its own sniffer's dialect as a bad delimiter value. The "
            "capability also reports the BOM, the duplicate `betrag` column and the "
            "ragged row, none of which Sniffer has an opinion about."
        ),
    ),
]


# ------------------------------------------------------------------- the runner


def run_capability(capability: str) -> dict[str, Any] | None:
    """Run the real thing over its own fixture, in a scratch directory."""
    import shutil
    import tempfile

    source = EXAMPLES / capability / "main.py"
    inputs = FIXTURES / capability / "inputs"
    if not source.is_file() or not inputs.is_dir():
        return None

    manifest = json.loads((ROOT / "capabilities" / "manifest.json").read_text(encoding="utf-8"))
    command = manifest["capabilities"][capability]["command"]
    argv = [sys.executable, str(source), *command[2:]]

    with tempfile.TemporaryDirectory() as work:
        for item in inputs.iterdir():
            shutil.copy2(item, Path(work) / item.name)
        completed = subprocess.run(argv, cwd=work, capture_output=True, text=True)
        if completed.returncode != 0:
            print(f"  ! {capability} exited {completed.returncode}: {completed.stderr[:200]}")
            return None
        produced = Path(work) / "result.json"
        if not produced.is_file():
            return None
        return dict(json.loads(produced.read_text(encoding="utf-8")))


def main() -> int:
    print(__doc__.split("\n\n")[0])
    print()

    divergences = 0
    unrunnable = 0
    for case in CASES:
        result = run_capability(case.capability)
        if result is None:
            print(f"{case.capability}: could not run")
            unrunnable += 1
            continue

        naive = case.naive()
        truth = case.truth(result)
        differs = naive != truth

        print(f"── {case.capability}")
        print(f"   {case.what}")
        print(f"   naive      {json.dumps(naive, sort_keys=True)}")
        print(f"   capability {json.dumps(truth, sort_keys=True)}")
        print(f"   {'DIVERGES' if differs else 'agrees'}  — {case.matters}")
        for note in case.notes:
            print(f"   note: {note}")
        print()
        divergences += 1 if differs else 0

    print(f"{divergences} of {len(CASES)} cases diverge.")
    print(
        "\nEach divergence is a plausible wrong answer, not a crash. That is what "
        "makes it worth recalling something proven rather than writing it again:\n"
        "a crash gets fixed, and a plausible wrong answer gets believed."
    )

    # Non-zero when a case stops diverging, so the claim cannot quietly rot the
    # way the corpus count and the egress suite did. A case that agrees means
    # either the capability regressed to the naive answer or the baseline was
    # weakened -- both are findings, and neither should exit 0.
    if unrunnable:
        print(f"\n{unrunnable} case(s) could not run at all.")
        return 1
    if divergences != len(CASES):
        print("\nA case agreed. Either the capability regressed or the baseline went soft.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
