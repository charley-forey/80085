"""Structurally validate a CSV file. Reads argv[1], writes result.json.

Checks the things that make a CSV unreadable rather than merely ugly: an
undecodable byte, a missing or duplicated header, and rows whose field count
does not match the header.

Exits 0 for a file it managed to inspect, even an invalid one. The sandbox
collects output files only from a successful run, so failing the process would
throw away the very report that says what is wrong.
"""

import csv
import io
import json
import sys


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def main() -> int:
    source = sys.argv[1]
    with open(source, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        finish(valid=False, errors=[f"byte {exc.start}: not valid UTF-8"], rows=0, columns=[])
        return 0

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        finish(valid=False, errors=["file is empty"], rows=0, columns=[])
        return 0

    errors = []
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate header columns: {duplicates}")
    if any(not name.strip() for name in header):
        errors.append("header contains an empty column name")

    rows = 0
    for number, row in enumerate(reader, start=2):
        rows += 1
        if len(row) != len(header):
            errors.append(f"line {number}: {len(row)} fields, header has {len(header)}")
    finish(valid=not errors, errors=errors, rows=rows, columns=header)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
