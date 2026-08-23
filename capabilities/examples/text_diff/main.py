"""Unified diff of two text files.

argv: <a> <b> <output.patch>

difflib's headers carry a file mtime by default, which would put the clock into
the output and make the same inputs hash differently on every run. They are
suppressed and the file names are used bare.

Exits 0 whether or not the files differ -- unlike diff(1), because here a
non-zero exit means the run failed and the patch would be discarded.
"""

import difflib
import hashlib
import json
import sys


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path: str) -> list[str]:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read().splitlines(keepends=True)


def main() -> int:
    left_path, right_path, output = sys.argv[1], sys.argv[2], sys.argv[3]
    left, right = read(left_path), read(right_path)
    lines = list(
        difflib.unified_diff(left, right, fromfile=left_path, tofile=right_path, lineterm="\n")
    )
    with open(output, "w", encoding="utf-8", newline="\n") as out:
        for line in lines:
            out.write(line if line.endswith("\n") else line + "\n")
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    finish(
        equal=not lines,
        added=added,
        removed=removed,
        output=output,
        sha256=digest(output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
