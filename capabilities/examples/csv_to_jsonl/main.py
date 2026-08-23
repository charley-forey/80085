"""CSV -> JSONL. Reads argv[1], writes argv[2], and always writes result.json.

result.json is what the verifier reads, so its bytes are pinned: sorted keys,
fixed separators, no timestamps and nothing else the environment can move.
"""

import csv
import hashlib
import json
import sys


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    rows = 0
    with (
        open(source, newline="", encoding="utf-8") as handle,
        open(target, "w", encoding="utf-8", newline="\n") as out,
    ):
        reader = csv.DictReader(handle)
        for row in reader:
            # Keys sorted and separators pinned: JSONL is line-addressable, so
            # a stable line is what makes a later diff or digest mean anything.
            out.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            rows += 1
        columns = list(reader.fieldnames or [])
    finish(rows=rows, columns=columns, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
