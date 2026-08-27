"""Total the sellable units in a Meridian Industries stock line list.

Three rules decide the answer and **none of them is in the file**:

    QUANTITY IS IN CASES OF TWELVE.   `30` is 360 units, not 30.
    GRADE K0 IS A REJECT.             It is stock, it is not sellable stock.
    REVISIONS BELOW 05 ARE OBSOLETE.  Tooling changed; they cannot be shipped.

A reader sees a quantity column and sums it. The number is well formed, it is
wrong by a factor of six, and no downstream system objects -- which is the only
failure mode that matters, because the loud ones get fixed.

Reads input.txt from the working directory, writes result.json.
"""

from __future__ import annotations

import json
from pathlib import Path

CASE_SIZE = 12
OLDEST_SHIPPABLE_REVISION = 5


def total(text: str) -> dict[str, object]:
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    rows: list[dict[str, object]] = []
    for line in lines:
        if "|" not in line:
            continue
        sku, quantity = (part.strip() for part in line.split("|", 1))
        parts = sku.split("-")
        if len(parts) != 4:
            continue
        _, item, revision, grade = parts
        obsolete = int(revision) < OLDEST_SHIPPABLE_REVISION
        reject = grade.upper() == "K0"
        cases = int(quantity)
        units = 0 if (obsolete or reject) else cases * CASE_SIZE
        rows.append(
            {
                "sku": sku,
                "item": item,
                "revision": int(revision),
                "grade": grade,
                "cases": cases,
                "units": units,
                "obsolete": obsolete,
                "reject": reject,
            }
        )
    return {
        "format": "MERIDIAN-STOCK-V2",
        "sellable_units": sum(int(r["units"]) for r in rows),
        "case_size": CASE_SIZE,
        "excluded_reject": sum(1 for r in rows if r["reject"]),
        "excluded_obsolete": sum(1 for r in rows if r["obsolete"]),
        "rows": rows,
    }


def main() -> None:
    text = Path("input.txt").read_text(encoding="utf-8")
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(total(text), out, indent=2, sort_keys=True)
        out.write("\n")


if __name__ == "__main__":
    main()
