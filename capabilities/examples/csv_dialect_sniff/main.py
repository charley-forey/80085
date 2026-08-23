"""Work out how a real-world CSV file is actually shaped, and report its damage.

argv: <input file>   ->  result.json

The CSV that arrives from a customer is a European export with semicolons and
comma decimals, or has a UTF-8 BOM glued to the first column name, or has
addresses with newlines inside quoted fields, or has three rows with the wrong
number of columns. Reading it with `csv.reader(open(path))` and defaults gives
no error and wrong data.

`csv.Sniffer` is the obvious tool and it is not used here: it decides from a
character-frequency heuristic over a text sample, so a file whose quoted
fields contain the rival delimiter can flip it, and a single-column file makes
it raise. Instead every candidate delimiter is used to parse the *whole* file
and scored on the only thing that matters -- whether it yields a consistent
number of fields per record. Wrong delimiters produce ragged output; that is
exactly the signal.

What this knows that a first attempt does not:

  * a BOM is not part of the first column name. `utf-8` leaves `\\ufeffid`,
    which silently breaks every lookup of `id` -- `utf-8-sig` is the fix;
  * records are not lines. A quoted field may contain newlines, so counting
    `\\n` overcounts rows, and `for line in file` splits records in half.
    Both counts are reported because they differ, and their difference is the
    number of embedded newlines;
  * a semicolon file usually means comma decimals: `1.234,56` is one number,
    and parsing it as a float without noticing gives 1.234 or an exception;
  * an odd number of double quotes means an unterminated field, after which
    every subsequent record is silently merged into one;
  * a duplicate or empty column name loses data on the way into a dict, which
    is where a CSV usually goes next;
  * a header is a guess, not a fact. It is inferred, and the inference is
    stated rather than assumed.
"""

import csv
import hashlib
import io
import json
import re
import sys

CANDIDATES = (",", ";", "\t", "|")
MAX_REPORTED_RAGGED = 50
DECIMAL_COMMA = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d+$|^-?\d+,\d{1,2}$")
NUMERIC = re.compile(r"^-?\d+([.,]\d+)?$")


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def parse(text: str, delimiter: str) -> list[list[str]] | None:
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error:
        return None


def score(records: list[list[str]]) -> tuple[int, float, int]:
    """(usable, share of records at the modal width, modal width). Higher is better."""
    if not records:
        return (0, 0.0, 0)
    widths = [len(record) for record in records]
    modal = max(sorted(set(widths)), key=widths.count)
    return (1 if modal > 1 else 0, widths.count(modal) / len(widths), modal)


def looks_like_header(records: list[list[str]], width: int) -> bool:
    """A header row is text where the rows below it are not."""
    if len(records) < 2:
        return False
    head = records[0]
    # Deliberately not requiring the names to be unique: a duplicated column is
    # damage worth reporting, and making it disqualify the header hides it.
    if len(head) != width or any(not cell.strip() for cell in head):
        return False
    if any(NUMERIC.match(cell.strip()) for cell in head):
        return False
    return any(
        NUMERIC.match(cell.strip()) for record in records[1:] for cell in record if cell.strip()
    )


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    notes: list[str] = []

    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        # utf-8-sig, never utf-8: the mark belongs to the file, not to column one.
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig" if bom else "utf-8"
    except UnicodeDecodeError:
        encoding = "cp1252"
        text = raw.decode("cp1252")
        notes.append(
            "the file is not utf-8; it was read as cp1252 to get a dialect out of it. "
            "Run encoding_detect before trusting any field value"
        )
    if bom:
        notes.append(
            "a utf-8 BOM precedes the header; read with utf-8 rather than utf-8-sig the first "
            "column name carries a leading \\ufeff and every lookup of it fails"
        )

    best: tuple[tuple[int, float, int], str, list[list[str]]] | None = None
    for delimiter in CANDIDATES:
        records = parse(text, delimiter)
        if records is None:
            continue
        ranked = score(records)
        if best is None or ranked > best[0]:
            best = (ranked, delimiter, records)
    if best is None:
        print("no candidate delimiter parses this file", file=sys.stderr)
        return 2
    (usable, share, width), delimiter, records = best
    if not usable:
        notes.append(
            "no delimiter splits this into more than one column; it is a single-column file "
            "or its delimiter is not one of " + " ".join(repr(c) for c in CANDIDATES)
        )
    if share < 1.0:
        notes.append(
            f"only {share:.0%} of records have the modal width of {width}; either rows are "
            "ragged or the delimiter is wrong"
        )

    ragged = [
        {"record": number, "fields": len(record)}
        for number, record in enumerate(records, start=1)
        if len(record) != width
    ]
    embedded = sum(1 for record in records for cell in record if "\n" in cell or "\r" in cell)
    if embedded:
        notes.append(
            f"{embedded} field(s) contain a newline inside quotes: records and lines are "
            "different counts here, and line-based reading would split records"
        )

    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    terminator = (
        "crlf" if crlf and not lf else "lf" if lf and not crlf else "mixed" if crlf else "none"
    )
    if terminator == "mixed":
        notes.append(f"line endings are mixed: {crlf} CRLF and {lf} bare LF")

    header = looks_like_header(records, width)
    columns = [cell.strip() for cell in records[0]] if header else []
    duplicates = sorted({name for name in columns if columns.count(name) > 1})
    if duplicates:
        notes.append(
            f"duplicate column name(s) {duplicates}: reading rows into a dict keeps only the "
            "last of each and loses the rest"
        )
    empty = [index for index, name in enumerate(columns) if not name]
    if not header:
        notes.append(
            "no header inferred: the first record is not distinguishable from the data "
            "below it, so column names must come from the caller"
        )

    decimal_comma = any(
        DECIMAL_COMMA.match(cell.strip())
        for record in records[1 if header else 0 :]
        for cell in record
    )
    if decimal_comma and delimiter == ";":
        notes.append(
            "semicolon-delimited with comma decimals -- a European export. float('1.234,56') "
            "raises, and stripping the dot first silently multiplies the value by 1000"
        )

    unbalanced = text.count('"') % 2 == 1
    if unbalanced:
        notes.append(
            "an odd number of double quotes: a field is left open, and every record after it "
            "is absorbed into that field rather than parsed"
        )

    finish(
        bom=bom,
        columns=columns,
        column_count=width,
        decimal_comma_suspected=decimal_comma,
        delimiter=delimiter,
        duplicate_columns=duplicates,
        embedded_newline_fields=embedded,
        empty_column_indexes=empty,
        encoding=encoding,
        has_header=header,
        line_terminator=terminator,
        notes=sorted(notes),
        physical_lines=text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        quotechar='"',
        ragged_count=len(ragged),
        ragged_records=ragged[:MAX_REPORTED_RAGGED],
        records=len(records),
        sha256=hashlib.sha256(raw).hexdigest(),
        unbalanced_quotes=unbalanced,
        width_consistency=round(share, 4),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
