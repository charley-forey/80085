"""JSONL -> CSV. Reads argv[1], writes argv[2] plus result.json.

Column order is first-seen rather than sorted: a CSV consumer reads columns
positionally, so reordering them silently would break every downstream reader.
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
    rows: list[dict[str, object]] = []
    columns: list[str] = []
    with open(source, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"line {number}: {exc}", file=sys.stderr)
                return 2
            if not isinstance(row, dict):
                print(f"line {number}: expected a JSON object", file=sys.stderr)
                return 2
            rows.append(row)
            for key in row:
                if key not in columns:
                    columns.append(key)
    with open(target, "w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    finish(rows=len(rows), columns=columns, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
