"""Settle a Northwind Freight remittance advice (NWF-REMIT-V3).

The point of this capability is that **none of its rules can be read off the
file**. A remittance advice from a specific counterparty is the canonical case
of knowledge an agent cannot reach by looking harder: the bytes are plain, the
structure is obvious, and every rule that decides the answer lives in a PDF
somebody was emailed in 2019.

    AMT is in TENTHS OF A CENT.        1234500 is $1234.50, not $12345.00.
    A TRAILING MINUS means credit.     45000- is a deduction, not a typo.
    ST=H is a HOLD, excluded.          It settles later, in another advice.
    REF carries a trailing CHECK LETTER, not part of the reference.

An agent handed this file will produce a total. It will be well formed, it will
be confidently wrong, and nothing downstream will flag it -- which is the whole
failure mode. There is no amount of reasoning that recovers "tenths of a cent"
from a column of integers.

Reads input.txt from /work, writes result.json.
"""

from __future__ import annotations

import json
from pathlib import Path

MAGIC = "NWF-REMIT-V3"


def settle(text: str) -> dict[str, object]:
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines or lines[0].strip() != MAGIC:
        return {"error": f"not a {MAGIC} advice", "settled_total_cents": None}

    account = None
    rows: list[dict[str, object]] = []
    for line in lines[1:]:
        parts = line.split("|")
        if parts[0] == "ACCT":
            account = parts[1].strip()
            continue
        if parts[0] == "REF":  # the header row, which is data-shaped
            continue
        if len(parts) < 3:
            continue
        reference, amount, status = parts[0].strip(), parts[1].strip(), parts[2].strip()

        # The trailing character of REF is a check letter, not the reference.
        stripped = reference[:-1] if reference and reference[-1].isalpha() else reference

        credit = amount.endswith("-")
        digits = amount[:-1] if credit else amount
        # Tenths of a cent. Integer division is deliberate: NWF never emits a
        # value that is not a whole number of cents, and a fractional cent here
        # means the file is malformed rather than that we should round it.
        cents = int(digits) // 10
        if credit:
            cents = -cents

        rows.append(
            {
                "reference": stripped,
                "check_letter": reference[len(stripped) :],
                "cents": cents,
                "status": status,
                "held": status == "H",
            }
        )

    settled = sum(int(r["cents"]) for r in rows if not r["held"])
    return {
        "format": MAGIC,
        "account": account,
        "settled_total_cents": settled,
        "held_count": sum(1 for r in rows if r["held"]),
        "held_total_cents": sum(int(r["cents"]) for r in rows if r["held"]),
        "row_count": len(rows),
        "rows": rows,
        "notes": [
            "amounts are tenths of a cent; a trailing minus is a credit",
            "ST=H rows are holds and settle in a later advice",
        ],
    }


def main() -> None:
    # Relative to the working directory, not an absolute /work. The sandbox
    # runs with /work as cwd and the capability test runs with a temp directory
    # as cwd, and a hardcoded path passes exactly one of those.
    text = Path("input.txt").read_text(encoding="utf-8")
    result = settle(text)
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write("\n")


if __name__ == "__main__":
    main()
