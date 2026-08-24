"""INI -> JSON. argv: input.ini output.json. Writes result.json.

configparser semantics, with two deliberate choices: key case is preserved
(the default lowercasing loses information), and [DEFAULT] values appear both
in their own object and merged into each section, because that is what they
mean to every INI reader.
"""

import configparser
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
    source, target = sys.argv[1], sys.argv[2]
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[method-assign,assignment]
    with open(source, encoding="utf-8") as handle:
        parser.read_file(handle)

    document: dict[str, dict[str, str]] = {}
    if parser.defaults():
        document["DEFAULT"] = dict(parser.defaults())
    for section in parser.sections():
        document[section] = dict(parser[section])

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump(document, out, indent=2, sort_keys=True)
        out.write("\n")
    keys = sum(len(values) for values in document.values())
    finish(sections=len(document), keys=keys, output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
