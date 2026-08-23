"""JSON array of objects -> CSV. Reads argv[1], writes argv[2] plus result.json.

The CSV itself cannot be verified beyond "the process exited zero", so the run
also writes result.json describing what it produced. That is what a verifier
reads: an exit code is satisfied by any container that returns 0.
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
    with open(source, encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        print("input must be a JSON array of objects", file=sys.stderr)
        return 2
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    finish(rows=len(rows), columns=columns, output=target, sha256=digest(target))
    print(f"converted {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
