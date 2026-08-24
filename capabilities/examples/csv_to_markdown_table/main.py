"""CSV -> Markdown table. argv: input.csv output.md. Writes result.json.

Pipes and newlines inside cells are what break naive attempts, so they are
the point: `|` is escaped and embedded newlines become spaces. The first row
is the header.
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


def cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if row]
    if not rows:
        raise SystemExit("the CSV has no rows")
    width = max(len(row) for row in rows)
    header, body = rows[0], rows[1:]

    def line(row: list[str]) -> str:
        padded = row + [""] * (width - len(row))
        return "| " + " | ".join(cell(value) for value in padded) + " |"

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write(line(header) + "\n")
        out.write("|" + "|".join([" --- "] * width) + "|\n")
        for row in body:
            out.write(line(row) + "\n")
    finish(rows=len(body), columns=width, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
