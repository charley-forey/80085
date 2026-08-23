"""Validate a JSON document against a JSON Schema subset. Reads argv[1]
(document) and argv[2] (schema), writes argv[3] with the verdict."""

import json
import sys


def check(document, schema, path="$"):
    errors = []
    expected = schema.get("type")
    kinds = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    if expected and not isinstance(document, kinds.get(expected, object)):
        return [f"{path}: expected {expected}"]
    if expected == "object":
        for key in schema.get("required", []):
            if key not in document:
                errors.append(f"{path}.{key}: required")
        for key, sub in schema.get("properties", {}).items():
            if key in document:
                errors.extend(check(document[key], sub, f"{path}.{key}"))
    elif expected == "array" and "items" in schema:
        for index, item in enumerate(document):
            errors.extend(check(item, schema["items"], f"{path}[{index}]"))
    return errors


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as handle:
        document = json.load(handle)
    with open(sys.argv[2], encoding="utf-8") as handle:
        schema = json.load(handle)
    errors = check(document, schema)
    with open(sys.argv[3], "w", encoding="utf-8") as handle:
        json.dump({"valid": not errors, "errors": errors}, handle, indent=2)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
