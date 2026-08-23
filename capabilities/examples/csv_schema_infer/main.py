"""Infer a JSON Schema for the rows of a CSV file.

argv: <input> <schema.json>

Types widen and never narrow -- one non-numeric value in a column of digits
makes the whole column a string. The alternative, guessing from the first row,
produces a schema that rejects the file it was inferred from.
"""

import csv
import hashlib
import json
import sys

BOOLEANS = {"true", "false"}


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def widen(current: str | None, value: str) -> str:
    """Least specific type that covers everything seen so far in a column."""
    if value.lower() in BOOLEANS:
        kind = "boolean"
    else:
        try:
            int(value)
            kind = "integer"
        except ValueError:
            try:
                float(value)
                kind = "number"
            except ValueError:
                kind = "string"
    if current is None or current == kind:
        return kind
    if {current, kind} == {"integer", "number"}:
        return "number"
    return "string"


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        types: dict[str, str | None] = dict.fromkeys(columns)
        nullable = dict.fromkeys(columns, False)
        rows = 0
        for row in reader:
            rows += 1
            for name in columns:
                value = (row.get(name) or "").strip()
                if not value:
                    nullable[name] = True
                    continue
                types[name] = widen(types[name], value)
    properties = {}
    for name in columns:
        kind = types[name] or "string"
        properties[name] = {"type": [kind, "null"] if nullable[name] else kind}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": [name for name in columns if not nullable[name]],
    }
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump(schema, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(
        rows=rows,
        columns=[
            {"name": name, "type": types[name] or "string", "nullable": nullable[name]}
            for name in columns
        ],
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
