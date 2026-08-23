"""JSON array of objects -> CSV. Reads argv[1], writes argv[2]."""

import csv
import json
import sys


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
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"converted {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
