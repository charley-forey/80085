"""Normalise line endings and strip a UTF-8 BOM.

argv: <input> <output> <lf|crlf|cr>

Mixed CRLF and LF in one file is the classic cause of a diff that shows every
line changed, and a leading BOM is the classic cause of a first column named
"﻿id". Both are fixed here in one pass.
"""

import hashlib
import json
import sys

ENDINGS = {"lf": b"\n", "crlf": b"\r\n", "cr": b"\r"}
BOM = b"\xef\xbb\xbf"


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    source, target, style = sys.argv[1], sys.argv[2], sys.argv[3]
    if style not in ENDINGS:
        print(f"style must be one of {sorted(ENDINGS)}", file=sys.stderr)
        return 2
    with open(source, "rb") as handle:
        raw = handle.read()
    bom_removed = raw.startswith(BOM)
    if bom_removed:
        raw = raw[len(BOM) :]
    # Collapse to LF first so CRLF is never split into two endings.
    lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    trailing = lines[-1] == b""
    if trailing:
        lines.pop()
    body = ENDINGS[style].join(lines) + (ENDINGS[style] if trailing else b"")
    with open(target, "wb") as out:
        out.write(body)
    finish(
        style=style,
        lines=len(lines),
        bom_removed=bom_removed,
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
