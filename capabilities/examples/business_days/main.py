"""Business-day arithmetic: the last one of the month, the Nth, and N from here.

argv: <input file>   ->  result.json

Input is JSON:
  {"weekend": [5, 6], "holidays": ["2024-12-25"], "observe_weekend_holidays": true,
   "queries": [{"kind": "last_business_day", "month": "2024-11"},
               {"kind": "nth_business_day", "month": "2024-11", "n": 3},
               {"kind": "add_business_days", "from": "2024-11-27", "days": 3},
               {"kind": "count_business_days", "from": "2024-11-01", "to": "2024-11-30"}]}

"Last business day of the month" is where payroll, invoicing and settlement
live, and it is almost never `monthrange()[1]`. The month can end on a
Saturday, on a public holiday, or on a holiday that is *observed* on a
different day from the one it falls on.

What this encodes:

  * **the observed-holiday rule.** A public holiday landing on a Saturday is
    normally taken on the Friday before and one landing on a Sunday on the
    Monday after. Christmas Day 2027 is a Saturday; the office is shut on the
    24th. A holiday list alone gets that wrong in both directions -- it closes
    a day that is open and opens a day that is shut -- so the observed dates
    are derived and reported alongside the ones that were given.
  * **the weekend is a parameter.** Friday and Saturday across much of the
    Gulf, Sunday only in parts of Asia. Hard-coding Saturday and Sunday is a
    quiet wrong answer rather than an error, so `weekend` is a list of Python
    weekday numbers with Monday as 0.
  * **adding zero business days is not a no-op.** From a Saturday it rolls
    forward to the next open day, which is what every "due in N days" rule
    means and what a naive loop returns unchanged.
  * **counting is inclusive of both ends**, stated here because half the
    disputes about a business-day count are about that and not about holidays.

Dates only, no zone and no clock: a business day is a calendar question, and
mixing an instant into it is how a day-boundary bug gets in.
"""

import calendar
import hashlib
import json
import sys
from datetime import date, timedelta

MAX_QUERIES = 200
MAX_SPAN_DAYS = 366 * 10
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


def observed(holiday: date, weekend: set[int]) -> date:
    """Where a holiday is actually taken when it falls on a closed day.

    Backwards to the previous open day for the first half of the weekend,
    forwards for the rest -- which for a Saturday/Sunday weekend is the
    familiar Friday/Monday pair, and stays sensible for a Friday/Saturday one.
    """
    if holiday.weekday() not in weekend:
        return holiday
    ordered = sorted(weekend)
    step = -1 if holiday.weekday() == ordered[0] else 1
    moved = holiday
    while moved.weekday() in weekend:
        moved += timedelta(days=step)
    return moved


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    weekend = {int(day) for day in request.get("weekend", [5, 6])}
    if not weekend <= set(range(7)) or len(weekend) >= 7:
        print(
            "weekend must be weekday numbers 0-6 (Monday is 0) and cannot be every day",
            file=sys.stderr,
        )
        return 2
    queries = request.get("queries", [])
    if len(queries) > MAX_QUERIES:
        print(f"at most {MAX_QUERIES} queries", file=sys.stderr)
        return 2

    given = [date.fromisoformat(value) for value in request.get("holidays", [])]
    observe = bool(request.get("observe_weekend_holidays", True))
    moved = []
    closed: set[date] = set()
    for holiday in given:
        taken = observed(holiday, weekend) if observe else holiday
        closed.add(taken)
        if taken != holiday:
            moved.append(
                {
                    "holiday": holiday.isoformat(),
                    "falls_on": DAY_NAMES[holiday.weekday()],
                    "observed": taken.isoformat(),
                }
            )

    def is_business(day: date) -> bool:
        return day.weekday() not in weekend and day not in closed

    results: list[dict[str, object]] = []
    for query in queries:
        kind = query["kind"]
        answer: date | None = None
        detail: dict[str, object] = {}
        if kind in {"last_business_day", "nth_business_day"}:
            year, month = (int(part) for part in str(query["month"]).split("-"))
            days = [
                date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)
            ]
            business = [day for day in days if is_business(day)]
            if kind == "last_business_day":
                answer = business[-1] if business else None
                detail = {
                    "calendar_last": days[-1].isoformat(),
                    # Everything between the answer and the end of the month is
                    # closed by construction; naming those days is what makes a
                    # 27th rather than a 31st reviewable.
                    "skipped": [day.isoformat() for day in days if answer is None or day > answer],
                }
            else:
                index = int(query["n"])
                answer = business[index - 1] if 0 < index <= len(business) else None
                detail = {"business_days_in_month": len(business)}
        elif kind == "add_business_days":
            start = date.fromisoformat(query["from"])
            days_to_add = int(query["days"])
            if abs(days_to_add) > MAX_SPAN_DAYS:
                print("refusing to walk more than ten years of business days", file=sys.stderr)
                return 2
            cursor = start
            rolled = False
            step = 1 if days_to_add >= 0 else -1
            # Zero means "the next open day", which from a Saturday is Monday.
            while not is_business(cursor):
                cursor += timedelta(days=step)
                rolled = True
            for _ in range(abs(days_to_add)):
                cursor += timedelta(days=step)
                while not is_business(cursor):
                    cursor += timedelta(days=step)
            answer = cursor
            detail = {
                "from": start.isoformat(),
                "days": days_to_add,
                "start_was_closed": rolled,
            }
        elif kind == "count_business_days":
            start = date.fromisoformat(query["from"])
            end = date.fromisoformat(query["to"])
            if abs((end - start).days) > MAX_SPAN_DAYS:
                print("refusing to count more than ten years of business days", file=sys.stderr)
                return 2
            low, high = sorted((start, end))
            total = 0
            cursor = low
            while cursor <= high:
                total += 1 if is_business(cursor) else 0
                cursor += timedelta(days=1)
            results.append(
                {
                    "kind": kind,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "count": total,
                    "inclusive": True,
                    "date": None,
                    "weekday": None,
                }
            )
            continue
        else:
            print(f"unknown query kind {kind!r}", file=sys.stderr)
            return 2

        results.append(
            {
                "kind": kind,
                "date": answer.isoformat() if answer else None,
                "weekday": DAY_NAMES[answer.weekday()] if answer else None,
                **detail,
            }
        )

    finish(
        weekend=sorted(weekend),
        weekend_days=[DAY_NAMES[day] for day in sorted(weekend)],
        holidays=[holiday.isoformat() for holiday in sorted(given)],
        observe_weekend_holidays=observe,
        observed_moves=moved,
        effective_closures=[day.isoformat() for day in sorted(closed)],
        queries=results,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
