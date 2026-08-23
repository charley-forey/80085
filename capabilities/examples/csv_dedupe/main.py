"""Drop duplicate CSV rows, keeping the first occurrence.

argv: <input> <output> [key columns, comma separated -- default: whole row]

First-occurrence-wins rather than last: the output then depends only on the
input, not on how many times a duplicate appears later in the file.
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
    key_columns = [name for name in sys.argv[3].split(",") if name] if len(sys.argv) > 3 else []
    with open(source, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        missing = [name for name in key_columns if name not in columns]
        if missing:
            print(f"key columns not in header: {missing}", file=sys.stderr)
            return 2
        keys = key_columns or columns
        seen: set[tuple[str, ...]] = set()
        kept: list[dict[str, str]] = []
        rows_in = 0
        for row in reader:
            rows_in += 1
            identity = tuple(row.get(name) or "" for name in keys)
            if identity in seen:
                continue
            seen.add(identity)
            kept.append(row)
    with open(target, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
    finish(
        rows_in=rows_in,
        rows_out=len(kept),
        duplicates_removed=rows_in - len(kept),
        key=keys,
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
