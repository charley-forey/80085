"""Parse dates, and refuse to guess when the string genuinely has two meanings.

argv: <input file>   ->  result.json

Input is JSON: {"values": ["03/04/2024", ...], "prefer": "none"|"dmy"|"mdy"}

`03/04/2024` is the 3rd of April in most of the world and the 4th of March in
the United States. Every library that parses it returns one answer. Whichever
it returns is wrong for half its callers, and it is wrong *silently* -- the
result is a valid date, so nothing downstream ever complains. A month-long
reporting error looks exactly like this.

So the answer here is a list of interpretations and an `ambiguous` flag. A
caller who knows the provenance passes `prefer`; a caller who does not is told
the value cannot be resolved, which is the true answer.

Everything else this encodes:

  * `13/04/2024` is *not* ambiguous -- 13 cannot be a month -- and a column of
    such values is how the convention for the whole file gets established.
    Those values are counted separately for exactly that purpose;
  * two-digit years are resolved by the POSIX pivot (69-99 -> 19xx,
    00-68 -> 20xx) and the assumption is stated, because that rule reads a
    mortgage ending in '69 as 2069 and a birth date of '70 as 1970;
  * `2024-02-30` and `2023-02-29` are invalid dates that look entirely
    ordinary, and a parser that rolls them onto the 1st of March is worse than
    one that fails;
  * ISO week dates sit up to three days away from where people assume:
    2021-W01-1 is 2021-01-04, and 2021-01-01 is 2020-W53-5;
  * a datetime with no offset names a wall clock, not an instant, and is
    flagged as not being a point in time;
  * `2024-3-4` is not ISO 8601 -- `fromisoformat` requires the zero padding --
    so it is read as a numeric date instead of reported as unparseable;
  * a zero-width no-break space is whitespace to a reader and not to
    `str.strip()`, so a padded value compares unequal to the same date.

Month names are English only, stated as a limit rather than resolved through a
locale: a container that reads the ambient locale answers differently on
different machines, which is the one thing an artifact may never do.
"""

import hashlib
import json
import re
import sys
from datetime import date, datetime

MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
# Non-breaking, narrow no-break, thin and figure spaces: whitespace to a reader,
# ordinary characters to str.strip().
WHITESPACE = " \t\r\n\v\f" + "".join(chr(point) for point in (0xA0, 0x2007, 0x2009, 0x202F, 0xFEFF))
NUMERIC = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})$")
DAY_FIRST = re.compile(r"^(\d{1,2})\s+([a-z]+)\.?,?\s+(\d{4})$")
MONTH_FIRST = re.compile(r"^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
NO_OFFSET = (
    "no UTC offset: this is a wall-clock reading, not an instant. Turning it into one "
    "needs the zone it was written in"
)


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def expand_year(year: int, digits: int, notes: list[str]) -> int:
    if digits > 2:
        return year
    expanded = 1900 + year if year >= 69 else 2000 + year
    notes.append(
        f"two-digit year {year:02d} read as {expanded} by the POSIX pivot (69-99 -> 19xx); "
        "a file that means the other century cannot be recovered from the value alone"
    )
    return expanded


def build(year: int, month: int, day: int) -> tuple[date | None, str]:
    try:
        return date(year, month, day), ""
    except ValueError:
        if not 1 <= month <= 12:
            return None, f"month {month} is out of range"
        reason = f"day {day} is out of range for month {month:02d} of {year}"
        if month == 2 and day == 29:
            reason += f" ({year} is not a leap year)"
        return None, reason


def numeric_readings(value: str, notes: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """Every reading of a slash/dot/dash date that names a real day, and why the rest do not."""
    match = NUMERIC.match(value)
    if not match:
        return [], []
    first, second, third = match.groups()
    if len(first) == 4:
        attempts = [("ymd", int(first), int(second), int(third))]
    else:
        year = expand_year(int(third), len(third), notes)
        attempts = [
            ("dmy", year, int(second), int(first)),
            ("mdy", year, int(first), int(second)),
        ]

    readings: list[dict[str, str]] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for order, year, month, day in attempts:
        parsed, reason = build(year, month, day)
        if parsed is None:
            if reason not in reasons:
                reasons.append(reason)
            continue
        # Two orders naming the same day are one interpretation, not an
        # ambiguity: 05/05/2024 reads identically either way.
        if parsed.isoformat() not in seen:
            seen.add(parsed.isoformat())
            readings.append({"order": order, "date": parsed.isoformat()})
    if len(attempts) == 2 and len(readings) == 1 and not reasons:
        readings[0]["order"] = "either"
    return readings, reasons


def textual_readings(value: str) -> list[dict[str, str]]:
    lowered = value.lower()
    match = DAY_FIRST.match(lowered)
    if match:
        day, name, year = match.group(1), match.group(2), match.group(3)
    else:
        match = MONTH_FIRST.match(lowered)
        if not match:
            return []
        name, day, year = match.group(1), match.group(2), match.group(3)
    month = MONTHS.get(name)
    if month is None:
        return []
    parsed, _ = build(int(year), month, int(day))
    return [{"order": "textual", "date": parsed.isoformat()}] if parsed else []


def iso_reading(value: str) -> tuple[str, str, bool] | None:
    """(kind, iso, has_offset) for a value ISO 8601 accepts, else None.

    Dates are tried first: `datetime.fromisoformat` accepts a bare date and
    hands back midnight, which invents a time of day the file never stated.
    """
    try:
        return "date", date.fromisoformat(value).isoformat(), False
    except ValueError:
        pass
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return "datetime", moment.isoformat(), moment.tzinfo is not None


def answer(
    value: str,
    *,
    iso: str | None,
    kind: str | None,
    ambiguous: bool,
    interpretations: list[dict[str, str]],
    has_offset: bool,
    reason: str | None,
    notes: list[str],
) -> dict[str, object]:
    return {
        "input": value,
        "iso": iso,
        "kind": kind,
        "ambiguous": ambiguous,
        "interpretations": interpretations,
        "has_offset": has_offset,
        "reason": reason,
        "notes": sorted(notes),
    }


def interpret(value: str, prefer: str) -> dict[str, object]:
    notes: list[str] = []
    cleaned = value.strip(WHITESPACE)
    if cleaned != value.strip():
        notes.append(
            "the value is padded with a zero-width no-break space or similar; Python's "
            "str.strip() leaves U+FEFF in place, and most other languages' trim() leaves the "
            "no-break space too, so the comparison downstream fails on invisible bytes"
        )

    reading = iso_reading(cleaned)
    if reading is not None:
        kind, iso, has_offset = reading
        if kind == "datetime" and not has_offset:
            notes.append(NO_OFFSET)
        if "W" in cleaned.upper():
            notes.append(
                "ISO week dates do not line up with the calendar year: week 1 is the week "
                "holding the first Thursday, so 2021-W01-1 is 2021-01-04"
            )
        return answer(
            value,
            iso=iso,
            kind=kind,
            ambiguous=False,
            interpretations=[{"order": "iso", "date": iso[:10]}],
            has_offset=has_offset,
            reason=None,
            notes=notes,
        )

    date_part, _, rest = cleaned.partition(" ")
    time_match = TIME.match(rest.strip()) if rest.strip() else None
    if rest.strip() and time_match is None:
        date_part = cleaned

    readings, reasons = numeric_readings(date_part, notes)
    if not readings and not reasons:
        readings = textual_readings(date_part)
    if not readings:
        return answer(
            value,
            iso=None,
            kind=None,
            ambiguous=False,
            interpretations=[],
            has_offset=False,
            reason="; ".join(reasons) or "not a recognised date format",
            notes=notes,
        )

    suffix, kind = "", "date"
    if time_match is not None:
        hour, minute, second = (int(part or 0) for part in time_match.groups())
        if hour <= 23 and minute <= 59 and second <= 59:
            suffix = f"T{hour:02d}:{minute:02d}:{second:02d}"
            kind = "datetime"
            notes.append(NO_OFFSET)
    interpretations = [{"order": item["order"], "date": item["date"] + suffix} for item in readings]

    if len(interpretations) == 1:
        order = interpretations[0]["order"]
        if order == "either":
            notes.append(
                "day and month are the same number here, so both conventions agree; the next "
                "value in this column may not be so forgiving"
            )
        elif order in {"dmy", "mdy"}:
            which = "first" if order == "dmy" else "second"
            notes.append(
                f"unambiguous only because the {which} number exceeds 12; other values in the "
                "same column will not be, so the convention has to be settled for the file"
            )
        return answer(
            value,
            iso=interpretations[0]["date"],
            kind=kind,
            ambiguous=False,
            interpretations=interpretations,
            has_offset=False,
            reason=None,
            notes=notes,
        )

    chosen = next((item for item in interpretations if item["order"] == prefer), None)
    if chosen is not None:
        notes.append(
            f"two readings name a real date; resolved by prefer={prefer}, which is the "
            "caller's knowledge of the source and not evidence from the value"
        )
        return answer(
            value,
            iso=chosen["date"],
            kind=kind,
            ambiguous=False,
            interpretations=interpretations,
            has_offset=False,
            reason=None,
            notes=notes,
        )
    notes.append(
        "both day-first and month-first name a real date, so this value has two meanings and "
        "the file does not say which. Pass prefer, or settle it from the whole column"
    )
    return answer(
        value,
        iso=None,
        kind=kind,
        ambiguous=True,
        interpretations=interpretations,
        has_offset=False,
        reason="ambiguous day/month order",
        notes=notes,
    )


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    prefer = request.get("prefer", "none")
    if prefer not in {"none", "dmy", "mdy"}:
        print("prefer must be none, dmy or mdy", file=sys.stderr)
        return 2

    results = [interpret(str(value), prefer) for value in request["values"]]
    # A column of these is what settles the convention for the whole file, so
    # they are counted rather than merely noted on each value.
    disambiguated = sum(
        1
        for item in results
        if isinstance(item["interpretations"], list)
        and len(item["interpretations"]) == 1
        and item["interpretations"][0]["order"] in {"dmy", "mdy"}
    )
    finish(
        prefer=prefer,
        count=len(results),
        ambiguous_count=sum(1 for item in results if item["ambiguous"]),
        unparsed_count=sum(1 for item in results if not item["interpretations"]),
        self_disambiguating_count=disambiguated,
        values=results,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
