"""Shift a local time, and be explicit about whether you meant a day or 24 hours.

argv: <input file>   ->  result.json

Input is JSON:
  {"zone": "America/New_York",
   "start": "2024-03-09T09:00:00",
   "shifts": [{"mode": "wall", "days": 1}, {"mode": "absolute", "hours": 24}]}

Across a DST transition "tomorrow at 9am" and "24 hours from now" are
different instants, and every scheduling bug of this family comes from code
that assumed they were the same. Both are computed here, side by side, with
the elapsed time in seconds, because seeing 82800 next to 86400 is the whole
lesson.

  * **wall** is calendar arithmetic. It is done on the *naive* local time and
    re-attached to the zone afterwards. Adding a timedelta to an aware
    datetime in Python does exactly this and looks like it does the other
    thing, which is the trap: the result keeps its wall clock and silently
    changes its UTC offset.
  * **absolute** is elapsed time. It is done in UTC and converted back, which
    is the only way to add "24 hours" and mean it.

Two local times need naming rather than resolving:

  * a **nonexistent** time -- 02:30 on the second Sunday of March in New York
    never happens. `datetime` will construct it anyway and quietly hand you an
    offset, so it is detected by round-tripping through UTC and compared, then
    pushed forward by the length of the gap, and both facts are reported.
  * an **ambiguous** time -- 01:30 on the first Sunday of November happens
    twice, an hour apart. PEP 495's `fold` picks which, and both instants are
    reported, because a system that logs one and reads back the other loses an
    hour of data once a year.

The tz database is the image's own copy, so an answer is pinned by the digest
the artifact is executed under. Rules for past dates change: two runs against
different tzdata releases can legitimately differ, and only the digest says
which release answered.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_SHIFTS = 200


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def is_nonexistent(naive: datetime, zone: ZoneInfo) -> bool:
    """True for a wall clock the zone skipped over.

    There is no flag to ask for. The test is that the local time does not
    survive a round trip through UTC: 02:30 becomes 03:30 coming back.
    """
    attached = naive.replace(tzinfo=zone)
    return attached.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive


def is_ambiguous(naive: datetime, zone: ZoneInfo) -> bool:
    """True for a wall clock the zone passed through twice."""
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    return first.utcoffset() != second.utcoffset() and not is_nonexistent(naive, zone)


def gap(naive: datetime, zone: ZoneInfo) -> timedelta:
    """How long the skipped interval is -- an hour nearly everywhere, 30 minutes on Lord Howe."""
    before = naive.replace(tzinfo=zone, fold=0).utcoffset()
    after = naive.replace(tzinfo=zone, fold=1).utcoffset()
    assert before is not None and after is not None
    return after - before


def describe(
    attached: datetime, zone: ZoneInfo, *, nonexistent: bool, resolution: str
) -> dict[str, object]:
    """Report an instant that has already been resolved. Never re-resolves it."""
    naive = attached.replace(tzinfo=None)
    ambiguous = is_ambiguous(naive, zone)
    alternate = None
    if ambiguous:
        other = naive.replace(tzinfo=zone, fold=1 - attached.fold)
        alternate = other.astimezone(UTC).isoformat()
    offset = attached.utcoffset()
    assert offset is not None
    seconds = int(abs(offset).total_seconds())
    return {
        "local": attached.isoformat(),
        "utc": attached.astimezone(UTC).isoformat(),
        "offset": f"{'-' if offset.total_seconds() < 0 else '+'}"
        f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}",
        "abbreviation": attached.tzname() or "",
        "nonexistent": nonexistent,
        "ambiguous": ambiguous,
        "ambiguous_alternate_utc": alternate,
        "resolution": resolution,
    }


def localize(naive: datetime, zone: ZoneInfo) -> dict[str, object]:
    """Attach the zone to a wall clock, saying what had to be decided to do it."""
    nonexistent = is_nonexistent(naive, zone)
    resolution = "none"
    if nonexistent:
        skipped = gap(naive, zone)
        naive = naive + skipped
        resolution = f"nonexistent local time; moved forward by the {skipped} gap"
    elif is_ambiguous(naive, zone):
        resolution = "ambiguous local time; took the first pass (fold=0)"
    return describe(
        naive.replace(tzinfo=zone, fold=0), zone, nonexistent=nonexistent, resolution=resolution
    )


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    zone = ZoneInfo(request["zone"])
    start = datetime.fromisoformat(request["start"])
    if start.tzinfo is not None:
        print("start must be a naive local time; the zone is given separately", file=sys.stderr)
        return 2
    shifts = request.get("shifts", [])
    if len(shifts) > MAX_SHIFTS:
        print(f"at most {MAX_SHIFTS} shifts", file=sys.stderr)
        return 2

    origin = localize(start, zone)
    origin_utc = datetime.fromisoformat(str(origin["utc"]))
    results = []
    for shift in shifts:
        mode = shift.get("mode", "wall")
        delta = timedelta(
            days=shift.get("days", 0),
            hours=shift.get("hours", 0),
            minutes=shift.get("minutes", 0),
        )
        if mode == "wall":
            # Calendar arithmetic: move the wall clock, then ask the zone what
            # that means. The offset is re-derived, so the elapsed time is not
            # what was added.
            moved = localize(start + delta, zone)
        elif mode == "absolute":
            # Elapsed arithmetic: move the instant, then ask what clock shows
            # it. The result is described, never re-localized -- stripping the
            # zone off an instant that landed in a repeated hour and attaching
            # it again picks fold=0 and moves the answer by an hour.
            moved = describe(
                (origin_utc + delta).astimezone(zone), zone, nonexistent=False, resolution="none"
            )
        else:
            print(f"mode must be wall or absolute, not {mode!r}", file=sys.stderr)
            return 2
        elapsed = datetime.fromisoformat(str(moved["utc"])) - origin_utc
        moved.update(
            {
                "mode": mode,
                "requested": {
                    "days": shift.get("days", 0),
                    "hours": shift.get("hours", 0),
                    "minutes": shift.get("minutes", 0),
                },
                "elapsed_seconds": int(elapsed.total_seconds()),
                "elapsed_matches_request": int(elapsed.total_seconds())
                == int(delta.total_seconds()),
            }
        )
        results.append(moved)

    finish(
        zone=request["zone"],
        start=origin,
        shifts=results,
        crossed_transition=any(shift["offset"] != origin["offset"] for shift in results),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
