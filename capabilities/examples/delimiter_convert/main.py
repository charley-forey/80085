"""Convert between delimited text formats without corrupting quoted fields.

argv: <input> <output> <from: csv|tsv|pipe|semicolon> <to: same set>

Re-delimiting with sed is the usual shortcut and it destroys every field that
contains the target delimiter. Round-tripping through the csv module recomputes
quoting for the new dialect instead.
"""

import csv
import hashlib
import json
import sys

DELIMITERS = {"csv": ",", "tsv": "\t", "pipe": "|", "semicolon": ";"}


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    source, target, source_format, target_format = sys.argv[1:5]
    if source_format not in DELIMITERS or target_format not in DELIMITERS:
        print(f"formats must be one of {sorted(DELIMITERS)}", file=sys.stderr)
        return 2
    rows = 0
    columns = 0
    with (
        open(source, newline="", encoding="utf-8") as handle,
        open(target, "w", newline="", encoding="utf-8") as out,
    ):
        reader = csv.reader(handle, delimiter=DELIMITERS[source_format])
        writer = csv.writer(out, delimiter=DELIMITERS[target_format], lineterminator="\n")
        for row in reader:
            writer.writerow(row)
            rows += 1
            columns = max(columns, len(row))
    finish(
        rows=rows,
        columns=columns,
        source_format=source_format,
        target_format=target_format,
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
