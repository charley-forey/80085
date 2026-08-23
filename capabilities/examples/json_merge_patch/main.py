"""Apply an RFC 7386 JSON Merge Patch.

argv: <target.json> <patch.json> <output.json>

Merge Patch, not JSON Patch: a patch is just a document, null means delete, and
arrays are replaced wholesale rather than merged element by element. That last
rule is the one people are surprised by, and it is the rule.
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


def merge(target: object, patch: object) -> object:
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge(result.get(key), value)
    return result


def load(path: str) -> object:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    target_path, patch_path, output = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        patched = merge(load(target_path), load(patch_path))
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 2
    with open(output, "w", encoding="utf-8", newline="\n") as out:
        json.dump(patched, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(output=output, sha256=digest(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
