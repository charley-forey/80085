"""Expand a recurring local appointment into the instants it actually happens at.

argv: <input file>   ->  result.json

Input is JSON:
  {"zone": "Europe/London", "start": "2024-03-28T09:30:00",
   "rule": "daily"|"weekly"|"monthly", "interval": 1, "count": 6}

A meeting recurs on the *wall clock*: 09:30 every day, in the office's own
zone. Its UTC instant therefore moves by an hour twice a year, and a schedule
expanded once into UTC and stored is wrong for half the year -- an hour early
every morning until somebody notices. Every occurrence here is generated in
local time and converted afterwards, which is the only order that survives a
transition.

The three things that go wrong, all reported per occurrence:

  * **the day the clocks change.** The local time is unchanged and the UTC
    instant is not. `utc_shifted` marks each occurrence whose offset differs
    from the one before it, which is the day a calendar and a cron job
    disagree.
  * **an occurrence that does not exist.** A 02:30 daily meeting has no 02:30
    on the morning the clocks go forward. It is moved forward by the length of
    the gap and flagged, rather than being silently given the offset that was
    in force the day before.
  * **the 31st of a month with 30 days.** Monthly recurrence clamps to the
    last day, and -- this is the part that is usually wrong -- the *next*
    month is computed from the original anchor day, not from the clamped one.
    Anchor on the clamped date and a schedule starting on the 31st of January
    collapses onto the 28th for the rest of its life.

Nothing here reads the clock: every occurrence is derived from `start`.
"""

import calendar
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_OCCURRENCES = 500
# Spelled out rather than taken from calendar.day_name, which formats through
# the ambient LC_TIME and would answer in whatever language the host is set to.
DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def is_nonexistent(naive: datetime, zone: ZoneInfo) -> bool:
    attached = naive.replace(tzinfo=zone)
    return attached.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive


def is_ambiguous(naive: datetime, zone: ZoneInfo) -> bool:
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    return first.utcoffset() != second.utcoffset() and not is_nonexistent(naive, zone)


def gap(naive: datetime, zone: ZoneInfo) -> timedelta:
    before = naive.replace(tzinfo=zone, fold=0).utcoffset()
    after = naive.replace(tzinfo=zone, fold=1).utcoffset()
    assert before is not None and after is not None
    return after - before


def add_months(start: datetime, months: int, anchor_day: int) -> tuple[datetime, bool]:
    """The same day-of-month `months` later, clamped to a short month. (when, clamped)."""
    total = start.year * 12 + (start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    day = min(anchor_day, last)
    return start.replace(year=year, month=month, day=day), day != anchor_day


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    zone = ZoneInfo(request["zone"])
    start = datetime.fromisoformat(request["start"])
    if start.tzinfo is not None:
        print("start must be a naive local time; the zone is given separately", file=sys.stderr)
        return 2
    rule = request.get("rule", "daily")
    interval = int(request.get("interval", 1))
    count = int(request.get("count", 1))
    if rule not in {"daily", "weekly", "monthly"}:
        print("rule must be daily, weekly or monthly", file=sys.stderr)
        return 2
    if interval < 1 or not 1 <= count <= MAX_OCCURRENCES:
        print(f"interval >= 1 and 1 <= count <= {MAX_OCCURRENCES}", file=sys.stderr)
        return 2

    anchor_day = start.day
    occurrences: list[dict[str, object]] = []
    previous_offset: str | None = None
    shifted = 0
    for index in range(count):
        clamped = False
        if rule == "monthly":
            naive, clamped = add_months(start, interval * index, anchor_day)
        else:
            days = interval * index * (7 if rule == "weekly" else 1)
            naive = start + timedelta(days=days)

        nonexistent = is_nonexistent(naive, zone)
        adjustment = "none"
        if nonexistent:
            skipped = gap(naive, zone)
            naive = naive + skipped
            adjustment = f"local time does not exist; moved forward by {skipped}"
        ambiguous = is_ambiguous(naive, zone)
        if ambiguous:
            adjustment = "local time happens twice; took the first pass (fold=0)"
        attached = naive.replace(tzinfo=zone, fold=0)
        offset = attached.utcoffset()
        assert offset is not None
        seconds = int(abs(offset).total_seconds())
        rendered = (
            f"{'-' if offset.total_seconds() < 0 else '+'}"
            f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
        )
        moved = previous_offset is not None and rendered != previous_offset
        shifted += 1 if moved else 0
        previous_offset = rendered
        occurrences.append(
            {
                "index": index,
                "local": attached.isoformat(),
                "utc": attached.astimezone(UTC).isoformat(),
                "offset": rendered,
                "abbreviation": attached.tzname() or "",
                "weekday": DAY_NAMES[attached.weekday()],
                "nonexistent": nonexistent,
                "ambiguous": ambiguous,
                "ambiguous_alternate_utc": (
                    naive.replace(tzinfo=zone, fold=1).astimezone(UTC).isoformat()
                    if ambiguous
                    else None
                ),
                "clamped": clamped,
                "utc_shifted": moved,
                "adjustment": adjustment,
            }
        )

    notes = []
    if shifted:
        notes.append(
            f"{shifted} occurrence(s) keep the same local time and change UTC instant: a "
            "schedule expanded once into UTC and stored would be an hour out from there on"
        )
    if any(item["clamped"] for item in occurrences):
        notes.append(
            f"day {anchor_day} does not exist in every month; those occurrences are clamped to "
            "the last day, and each following month is still computed from day "
            f"{anchor_day} rather than from the clamped date"
        )
    if any(item["nonexistent"] for item in occurrences):
        notes.append(
            "an occurrence fell in the hour the clocks skipped; it was moved forward rather "
            "than given the previous day's offset"
        )
    finish(
        zone=request["zone"],
        rule=rule,
        interval=interval,
        count=count,
        anchor_day=anchor_day,
        occurrences=occurrences,
        utc_shifts=shifted,
        notes=sorted(notes),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
