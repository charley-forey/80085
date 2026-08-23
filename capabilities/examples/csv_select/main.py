"""Project and rename CSV columns from a declarative spec.

argv: <input> <output> <spec.json>
spec: {"select": ["a", "b"], "rename": {"a": "alpha"}}   -- both optional

A missing column is an error rather than an empty column: silently emitting
blanks is how a broken pipeline gets discovered three stages downstream.
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
    source, target, spec_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    rename = spec.get("rename") or {}
    with open(source, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        available = list(reader.fieldnames or [])
        selected = list(spec.get("select") or available)
        missing = [name for name in [*selected, *rename] if name not in available]
        if missing:
            print(f"columns not in header: {sorted(set(missing))}", file=sys.stderr)
            return 2
        columns = [rename.get(name, name) for name in selected]
        rows = 0
        with open(target, "w", newline="", encoding="utf-8") as out:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(columns)
            for row in reader:
                writer.writerow([row.get(name) or "" for name in selected])
                rows += 1
    finish(rows=rows, columns=columns, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
