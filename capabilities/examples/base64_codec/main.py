"""Base64 encode or decode a file.

argv: <input> <output> <encode|decode> [standard|urlsafe]

Encoding emits one unbroken line: line-wrapped base64 differs between tools at
64 and 76 columns, and that difference alone would change the output digest.
"""

import base64
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


def main() -> int:
    source, target, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    alphabet = sys.argv[4] if len(sys.argv) > 4 else "standard"
    if mode not in {"encode", "decode"} or alphabet not in {"standard", "urlsafe"}:
        print("argv: <input> <output> <encode|decode> [standard|urlsafe]", file=sys.stderr)
        return 2
    with open(source, "rb") as handle:
        raw = handle.read()
    try:
        if mode == "encode":
            coded = (
                base64.urlsafe_b64encode(raw) if alphabet == "urlsafe" else base64.b64encode(raw)
            )
        else:
            stripped = b"".join(raw.split())
            coded = (
                base64.urlsafe_b64decode(stripped)
                if alphabet == "urlsafe"
                # validate=True so stray non-alphabet bytes are an error rather
                # than silently discarded, which would decode garbage as data.
                else base64.b64decode(stripped, validate=True)
            )
    except ValueError as exc:  # binascii.Error is a ValueError subclass
        print(f"{mode} failed: {exc}", file=sys.stderr)
        return 2
    with open(target, "wb") as out:
        out.write(coded)
    finish(
        mode=mode,
        alphabet=alphabet,
        bytes_in=len(raw),
        bytes_out=len(coded),
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
