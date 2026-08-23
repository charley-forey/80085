"""Identify how a text file is encoded, and say so when the answer is a guess.

argv: <input file>   ->  result.json

A wrong encoding guess does not fail. It produces text that looks almost
right, corrupts one character in a hundred, and is discovered months later in
a database. So this reports three separate things -- what the bytes prove,
what was inferred, and where two encodings are indistinguishable -- instead of
one confident string.

The order of the checks is itself the knowledge:

  * the UTF-32LE BOM *starts with* the UTF-16LE BOM. Test the short one first
    and every UTF-32LE file is reported as UTF-16LE full of NULs;
  * pure ASCII proves nothing. UTF-8, cp1252 and latin-1 all agree on it, so
    it is reported as `ascii` and `ambiguous`, never as "UTF-8";
  * valid UTF-8 containing a multi-byte sequence is near proof -- the
    continuation-byte structure is far too strict to hit by accident;
  * cp1252 has five undefined bytes (0x81 0x8D 0x8F 0x90 0x9D). Finding one
    rules cp1252 out. Not finding one rules nothing in;
  * from 0xA0 to 0xFF cp1252 *is* latin-1, so a file that only uses those
    decodes identically under both and the question has no answer;
  * bytes 0x80-0x9F are printable in cp1252 and C1 control characters in
    latin-1. Real text does not contain C1 controls, so their presence is the
    only evidence that separates the two;
  * valid UTF-8 can still be wrong. Mojibake is valid UTF-8 by construction --
    that is what makes it survive -- so it is detected here and repaired by
    `mojibake_repair`, not silently fixed;
  * one bad line in an otherwise UTF-8 file is a real thing (a log with a
    single latin-1 record). Whole-file decoding calls that "not UTF-8", which
    is true and useless; the line numbers are the answer.
"""

import hashlib
import json
import sys

# Longest first: b"\xff\xfe\x00\x00" (UTF-32LE) begins with b"\xff\xfe" (UTF-16LE).
BOMS = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)
UNMAPPED_CP1252 = (0x81, 0x8D, 0x8F, 0x90, 0x9D)
MAX_REPORTED_LINES = 20


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def looks_like_mojibake(text: str) -> bool:
    """True if this text is UTF-8 bytes that were once decoded as a legacy codec.

    The discriminator is not a list of suspicious characters -- French text is
    full of those. It is that re-encoding the text under the legacy codec
    yields bytes that are *valid UTF-8*, which ordinary latin text does not:
    "café" -> b"caf\xe9" is not valid UTF-8, while "Ã©" -> b"\xc3\xa9" is.
    """
    if text.isascii():
        return False
    for legacy in ("cp1252", "latin-1"):
        try:
            raw = text.encode(legacy)
        except UnicodeEncodeError:
            continue
        try:
            repaired = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if repaired != text:
            return True
    return False


def line_survey(raw: bytes) -> tuple[list[int], int]:
    """1-based lines that are not UTF-8, and how many lines are multi-byte UTF-8.

    Both halves are needed to tell "this file is latin-1" from "this file is
    UTF-8 with one latin-1 record in it", which are the same whole-file failure
    and completely different problems.
    """
    bad = []
    multibyte = 0
    for number, line in enumerate(raw.split(b"\n"), start=1):
        try:
            line.decode("utf-8")
        except UnicodeDecodeError:
            bad.append(number)
            continue
        if not line.isascii():
            multibyte += 1
    return bad, multibyte


def report(
    *,
    raw: bytes,
    encoding: str,
    confidence: str,
    ambiguous: bool,
    alternatives: list[str],
    decodable: bool,
    text: str | None,
    notes: list[str],
) -> None:
    bad, multibyte = line_survey(raw)
    mixed = bool(bad) and multibyte > 0
    if mixed:
        notes.append(
            f"{multibyte} line(s) are genuine multi-byte utf-8 and {len(bad)} do not decode at "
            "all: this file is not in one encoding, and no single answer is right for it"
        )
    if len(bad) > MAX_REPORTED_LINES:
        notes.append(f"{len(bad)} lines are not utf-8; the first {MAX_REPORTED_LINES} are listed")
    finish(
        encoding=encoding,
        bom=next((name for marker, name in BOMS if raw.startswith(marker)), None),
        confidence=confidence,
        ambiguous=ambiguous,
        alternatives=sorted(alternatives),
        decodable=decodable,
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        mojibake_suspected=bool(text is not None and looks_like_mojibake(text)),
        undecodable_lines=bad[:MAX_REPORTED_LINES],
        mixed_encoding=mixed,
        notes=sorted(notes),
    )


def decode(raw: bytes, codec: str) -> str | None:
    try:
        return raw.decode(codec)
    except (UnicodeDecodeError, LookupError):
        return None


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()

    for marker, name in BOMS:
        if raw.startswith(marker):
            # Decode the body, not the mark: `raw.decode("utf-16-le")` on bytes
            # that still carry their BOM leaves a U+FEFF at the front of the
            # text, which then travels into whatever consumes it.
            text = decode(raw[len(marker) :], "utf-8" if name == "utf-8-sig" else name)
            notes = ["a byte order mark names the encoding; nothing here is inferred"]
            if text is None:
                notes.append(f"the {name} BOM is present but the rest does not decode as {name}")
            report(
                raw=raw,
                encoding=name,
                confidence="certain",
                ambiguous=False,
                alternatives=[],
                decodable=text is not None,
                text=text,
                notes=notes,
            )
            return 0

    if not raw:
        report(
            raw=raw,
            encoding="ascii",
            confidence="low",
            ambiguous=True,
            alternatives=["cp1252", "latin-1", "utf-8"],
            decodable=True,
            text="",
            notes=["the file is empty; every encoding decodes it to nothing"],
        )
        return 0

    text = decode(raw, "utf-8")
    if text is not None and raw.isascii():
        report(
            raw=raw,
            encoding="ascii",
            confidence="certain",
            ambiguous=True,
            alternatives=["cp1252", "latin-1", "utf-8"],
            decodable=True,
            text=text,
            notes=[
                "every byte is below 0x80, so utf-8, cp1252 and latin-1 all "
                "produce identical text; the file carries no evidence of which was intended"
            ],
        )
        return 0
    if text is not None:
        notes = ["valid utf-8 with multi-byte sequences; hitting that by accident is implausible"]
        if looks_like_mojibake(text):
            notes.append(
                "the text is valid utf-8 and still wrong: it re-encodes to valid utf-8 under a "
                "legacy codec, which is what mojibake looks like. Repair with mojibake_repair"
            )
        report(
            raw=raw,
            encoding="utf-8",
            confidence="high",
            ambiguous=False,
            alternatives=[],
            decodable=True,
            text=text,
            notes=notes,
        )
        return 0

    # Not UTF-8. BOM-less UTF-16 is the next most likely thing, and it is the
    # one case where NUL bytes are signal rather than corruption.
    nulls = raw.count(0)
    if nulls * 4 >= len(raw):
        odd = sum(1 for index in range(1, len(raw), 2) if raw[index] == 0)
        codec = "utf-16-le" if odd * 2 >= nulls else "utf-16-be"
        decoded = decode(raw, codec)
        report(
            raw=raw,
            encoding=codec,
            confidence="low",
            ambiguous=True,
            alternatives=["utf-16-be", "utf-16-le"],
            decodable=decoded is not None,
            text=decoded,
            notes=[
                f"{nulls} of {len(raw)} bytes are NUL and there is no BOM; byte order was "
                "inferred from which half of each pair holds the NUL, which fails on text "
                "that is mostly non-Latin"
            ],
        )
        return 0

    unmapped = sorted({byte for byte in raw if byte in UNMAPPED_CP1252})
    control = any(0x80 <= byte <= 0x9F and byte not in UNMAPPED_CP1252 for byte in raw)
    if unmapped:
        encoding, alternatives = "latin-1", []
        notes = [
            "cp1252 is ruled out: "
            + ", ".join(f"0x{byte:02x}" for byte in unmapped)
            + " is undefined in cp1252 and every other single-byte codec accepts it"
        ]
    elif control:
        encoding, alternatives = "cp1252", ["latin-1"]
        notes = [
            "bytes in 0x80-0x9f are printable punctuation in cp1252 and C1 control "
            "characters in latin-1; real text does not contain C1 controls"
        ]
    else:
        encoding, alternatives = "cp1252", ["latin-1"]
        notes = [
            "only bytes >= 0xa0 are used, where cp1252 and latin-1 are the same table: "
            "the two decode this file identically and the distinction is not decidable"
        ]
    report(
        raw=raw,
        encoding=encoding,
        confidence="low",
        ambiguous=True,
        alternatives=alternatives,
        decodable=True,
        text=decode(raw, encoding),
        notes=notes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
