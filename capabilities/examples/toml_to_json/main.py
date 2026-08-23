"""TOML -> JSON. Reads argv[1], writes argv[2] plus result.json.

TOML has dates and times, JSON does not, so they are emitted as ISO 8601
strings -- lossy in type, faithful in value, and the only thing a JSON consumer
can read back.
"""

import datetime as dt
import hashlib
import json
import sys
import tomllib


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def encode(value: object) -> str:
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__} as JSON")


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, "rb") as handle:
        try:
            document = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            print(f"invalid TOML: {exc}", file=sys.stderr)
            return 2
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump(document, out, indent=2, sort_keys=True, default=encode)
        out.write("\n")
    finish(keys=sorted(document), output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
