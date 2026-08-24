"""Next run times of a cron expression. argv: input.json output.json.

input.json: {"cron": "m h dom mon dow", "start": ISO-8601 UTC, "count": N}.
Classic five-field cron: lists, ranges, steps, *; dow 0-7 with both 0 and 7
meaning Sunday; the standard rule that a restricted day-of-month and a
restricted day-of-week match on either. Minute resolution, strictly after
`start`, searched at most five years out.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def parse_field(field: str, low: int, high: int, sunday_wraps: bool) -> set[int]:
    allowed: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            step = int(raw_step)
            if step < 1:
                raise ValueError(f"step must be positive: {raw_step}")
        if part == "*" or part == "":
            start, end = low, high
        elif "-" in part:
            raw_start, raw_end = part.split("-", 1)
            start, end = int(raw_start), int(raw_end)
        else:
            start = end = int(part)
        if not (low <= start <= high and low <= end <= high and start <= end):
            raise ValueError(f"field out of range: {part} not in {low}-{high}")
        allowed.update(range(start, end + 1, step))
    if sunday_wraps and 7 in allowed:
        allowed.discard(7)
        allowed.add(0)
    return allowed


def matches(
    moment: datetime, fields: list[set[int]], dom_restricted: bool, dow_restricted: bool
) -> bool:
    minute, hour, dom, mon, dow = fields
    if moment.minute not in minute or moment.hour not in hour or moment.month not in mon:
        return False
    day_ok = moment.day in dom
    # cron counts Sunday as 0; datetime counts Monday as 0.
    weekday_ok = (moment.weekday() + 1) % 7 in dow
    if dom_restricted and dow_restricted:
        return day_ok or weekday_ok
    return day_ok and weekday_ok


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as handle:
        spec = json.load(handle)

    parts = str(spec["cron"]).split()
    if len(parts) != 5:
        raise SystemExit(f"expected 5 cron fields, got {len(parts)}")
    fields = [
        parse_field(part, low, high, index == 4)
        for index, (part, (low, high)) in enumerate(zip(parts, BOUNDS, strict=True))
    ]
    count = int(spec.get("count", 5))
    if not 1 <= count <= 100:
        raise SystemExit("count must be between 1 and 100")

    start = datetime.fromisoformat(str(spec["start"]).replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    start = start.astimezone(UTC)

    moment = (start + timedelta(minutes=1)).replace(second=0, microsecond=0)
    horizon = start + timedelta(days=5 * 366)
    dom_restricted, dow_restricted = parts[2] != "*", parts[4] != "*"

    runs: list[str] = []
    while len(runs) < count and moment <= horizon:
        if matches(moment, fields, dom_restricted, dow_restricted):
            runs.append(moment.strftime("%Y-%m-%dT%H:%M:%SZ"))
        moment += timedelta(minutes=1)
    if len(runs) < count:
        raise SystemExit("cron expression never fires within five years")

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump({"cron": spec["cron"], "runs": runs}, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(count=len(runs), first=runs[0], last=runs[-1], output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
