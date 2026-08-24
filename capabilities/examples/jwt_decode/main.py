"""Decode a JWT's header and payload. argv: input.txt output.json.

NO signature verification, on purpose, and the output says so: this is for
inspecting a token you already hold -- which claims it carries, which
algorithm it names, whether an expiry is present. Trusting an unverified
token is the caller's mistake to not make.
"""

import base64
import binascii
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


def b64url(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as handle:
        token = handle.read().strip()

    parts = token.split(".")
    if len(parts) != 3:
        raise SystemExit(f"a JWT has three dot-separated parts; this has {len(parts)}")
    try:
        header = json.loads(b64url(parts[0]))
        payload = json.loads(b64url(parts[1]))
        signature = b64url(parts[2]) if parts[2] else b""
    except (binascii.Error, ValueError) as error:
        raise SystemExit(f"not base64url-encoded JSON: {error}") from error

    document = {
        "header": header,
        "payload": payload,
        "signature_bytes": len(signature),
        "verified": False,
    }
    with open(target, "w", encoding="utf-8", newline="\n") as out:
        json.dump(document, out, indent=2, sort_keys=True)
        out.write("\n")
    finish(
        algorithm=str(header.get("alg", "")),
        claims=len(payload) if isinstance(payload, dict) else 0,
        output=target,
        sha256=digest(target),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
