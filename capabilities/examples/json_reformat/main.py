"""Pretty-print or minify JSON. Reads argv[1], writes argv[2] plus result.json.

argv: <input> <output> <pretty|minify>

Keys are sorted in both modes. That is a deliberate normalisation rather than a
faithful reproduction: two documents that differ only in key order should
produce the same bytes, which is what makes the output diffable and hashable.
"""

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
    if mode not in {"pretty", "minify"}:
        print("mode must be pretty or minify", file=sys.stderr)
        return 2
    with open(source, encoding="utf-8") as handle:
        try:
            document = json.load(handle)
        except json.JSONDecodeError as exc:
            print(f"invalid JSON: {exc}", file=sys.stderr)
            return 2
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        if mode == "pretty":
            json.dump(document, out, indent=2, sort_keys=True)
            out.write("\n")
        else:
            json.dump(document, out, sort_keys=True, separators=(",", ":"))
    finish(mode=mode, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
