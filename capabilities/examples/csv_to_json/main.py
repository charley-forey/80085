"""CSV -> JSON. Reads argv[1] from the working directory, writes argv[2].

Deliberately stdlib-only: an artifact with no dependencies has no supply
chain, which is the right place to start when every artifact is untrusted.
"""

import csv
import json
import sys


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    # newline="\n" or the same code emits CRLF on Windows and LF on Linux, and
    # an artifact whose bytes depend on where it ran cannot be evidence.
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
    print(f"converted {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
