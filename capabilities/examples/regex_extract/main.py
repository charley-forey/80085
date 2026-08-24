"""Extract every regex match from a text file. argv: spec.json input.txt output.json.

spec.json: {"pattern": str, "flags": "im"?, "group": int?, "max_matches": int?}.
Flags are single letters: i, m, s, x. `group` selects a capture group
(default 0, the whole match). Matches come back in order, de-duplication left
to the caller because sometimes the duplicates are the answer.
"""

import hashlib
import json
import re
import sys


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}


def main() -> int:
    spec_path, source, target = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)

    flags = 0
    for letter in str(spec.get("flags", "")):
        if letter not in FLAGS:
            raise SystemExit(f"unknown flag {letter!r}; known: {''.join(sorted(FLAGS))}")
        flags |= FLAGS[letter]
    try:
        pattern = re.compile(str(spec["pattern"]), flags)
    except re.error as error:
        raise SystemExit(f"bad pattern: {error}") from error
    group = int(spec.get("group", 0))
    if not 0 <= group <= pattern.groups:
        raise SystemExit(f"group {group} but the pattern has {pattern.groups}")
    cap = int(spec.get("max_matches", 1000))

    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    matches = []
    for found in pattern.finditer(text):
        matches.append(found.group(group))
        if len(matches) >= cap:
            break

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump({"count": len(matches), "matches": matches}, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(count=len(matches), truncated=len(matches) >= cap, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
