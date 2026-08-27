"""Resolve an Orbital Systems part number through its supersession chain.

The chain is in the file. The rule that decides the answer is not:

    A PART IS NOT VALID OUTSIDE ITS REGION.

So the end of the chain is the right answer only when the end of the chain is
sellable where the order is. For a US order whose chain terminates in an
EU-only part, the correct part is the last US-valid one *before* it -- which
looks, to anyone reading the file, like deliberately shipping a superseded
part.

Reads input.txt from the working directory, writes result.json.
"""

from __future__ import annotations

import json
from pathlib import Path

GLOBAL = "GLOBAL"


def resolve(text: str) -> dict[str, object]:
    chain: list[str] = []
    region: dict[str, str] = {}
    order_part = order_region = ""
    for line in text.replace("\r\n", "\n").split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if parts[0] == "CHAIN":
            chain = [p.strip() for p in parts[1].split(">")]
        elif parts[0] == "REGION" and len(parts) == 3:
            region[parts[1]] = parts[2]
        elif parts[0] == "ORDER" and len(parts) == 3:
            order_part, order_region = parts[1], parts[2]

    start = chain.index(order_part) if order_part in chain else 0
    # Walk to the end, then back to the newest part this order may actually be
    # shipped: a superseded part that is sellable beats a current one that is not.
    resolved = order_part
    for candidate in chain[start:]:
        where = region.get(candidate, GLOBAL)
        if where in (GLOBAL, order_region):
            resolved = candidate
    return {
        "format": "ORBITAL-SUPERSEDE-V1",
        "ordered_part": order_part,
        "order_region": order_region,
        "resolved_part": resolved,
        "chain_end": chain[-1] if chain else None,
        "blocked_by_region": [
            p for p in chain if region.get(p, GLOBAL) not in (GLOBAL, order_region)
        ],
    }


def main() -> None:
    text = Path("input.txt").read_text(encoding="utf-8")
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(resolve(text), out, indent=2, sort_keys=True)
        out.write("\n")


if __name__ == "__main__":
    main()
