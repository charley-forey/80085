"""XML -> JSON. Reads argv[1], writes argv[2] plus result.json.

The input is hostile, and XML is the format with the richest history of turning
a parser into a file-read primitive or an exponential memory bomb. Two cheap
refusals do most of the work: no DOCTYPE at all, which removes entity
expansion and external entities together, and a hard byte ceiling.

Structure is explicit -- tag, attributes, text, children -- rather than the
usual "collapse single children into scalars" convention, because that
convention makes the shape of the output depend on the data.
"""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET

MAX_BYTES = 8 * 1024 * 1024


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def convert(element: ET.Element) -> dict[str, object]:
    text = (element.text or "").strip()
    return {
        "tag": element.tag,
        "attributes": dict(sorted(element.attrib.items())),
        "text": text,
        "children": [convert(child) for child in element],
    }


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, "rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        print(f"input exceeds {MAX_BYTES} bytes", file=sys.stderr)
        return 2
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        print("refusing XML with a DOCTYPE or entity declaration", file=sys.stderr)
        return 2
    try:
        root = ET.fromstring(raw)  # noqa: S314 - DOCTYPE refused above
    except ET.ParseError as exc:
        print(f"invalid XML: {exc}", file=sys.stderr)
        return 2
    document = convert(root)
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump(document, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(root=root.tag, bytes_in=len(raw), output=target, sha256=digest(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
