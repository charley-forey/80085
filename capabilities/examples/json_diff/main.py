"""Structural diff of two JSON documents. Reads argv[1] and argv[2], writes
result.json.

A textual diff of two JSON files reports key order and indentation as changes,
which is noise. This compares values at a path and reports added, removed and
changed, sorted by path so the report itself is stable.

Exits 0 whether or not the documents differ: "they differ" is an answer, not a
failure, and a non-zero exit would throw the report away.
"""

import json
import sys


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def walk(left: object, right: object, path: str, changes: list[dict[str, object]]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}"
            if key not in right:
                changes.append({"path": child, "op": "removed", "from": left[key]})
            elif key not in left:
                changes.append({"path": child, "op": "added", "to": right[key]})
            else:
                walk(left[key], right[key], child, changes)
        return
    if isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            if index >= len(right):
                changes.append({"path": child, "op": "removed", "from": left[index]})
            elif index >= len(left):
                changes.append({"path": child, "op": "added", "to": right[index]})
            else:
                walk(left[index], right[index], child, changes)
        return
    # bool is a subclass of int, so 1 == True: compare types too or the diff
    # quietly calls a boolean flag and the number one identical.
    if left != right or type(left) is not type(right):
        changes.append({"path": path, "op": "changed", "from": left, "to": right})


def load(path: str) -> object:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    try:
        left, right = load(sys.argv[1]), load(sys.argv[2])
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 2
    changes: list[dict[str, object]] = []
    walk(left, right, "$", changes)
    changes.sort(key=lambda change: str(change["path"]))
    finish(equal=not changes, changes=changes, change_count=len(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
