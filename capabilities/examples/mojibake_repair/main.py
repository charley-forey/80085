"""Repair text that was decoded as the wrong codec and re-saved as UTF-8.

argv: <input file> <output file>   ->  output + result.json

`Ã©` for `é`, `â€™` for `’`, `Â ` for a non-breaking space. UTF-8 bytes read
as cp1252 and written back out as UTF-8: valid UTF-8 at every step, so nothing
downstream ever errors, and the damage is invisible until somebody reads it.

The repair is the inverse: encode the text back to the legacy codec and decode
those bytes as UTF-8. Four things about doing it in production make the
difference between a fix and a second corruption, and all four are here.

  * **Only accept a pass that provably reverses.** A run is repaired only if
    it re-encodes without loss and the resulting bytes are *valid UTF-8*.
    Ordinary accented text fails that test -- b"caf\\xe9" is not valid UTF-8 --
    so clean text is left alone and running this twice is a no-op. That is
    what makes it safe to run on a corpus that is only partly damaged.
  * **Repair runs, not documents.** `text.encode("cp1252")` raises on the
    first character cp1252 cannot hold, so a document that is 99% intact plus
    one emoji fails whole-document repair entirely. Real files are mixed, so
    each maximal run of legacy-encodable characters is repaired on its own.
    A mojibake sequence is always entirely such characters -- every byte of a
    multi-byte UTF-8 sequence is >= 0x80 -- so runs never split one.
  * **Try latin-1 as well as cp1252.** cp1252 has five undefined bytes
    (0x81 0x8D 0x8F 0x90 0x9D) and they appear in real UTF-8 continuation
    bytes, so any sequence containing one was mangled through latin-1 and
    cannot be repaired as cp1252.
  * **Iterate, with a ceiling.** Text that went through the wrong codec twice
    needs two passes (`Ã\\u0083Â©`). A bounded loop repairs it; an unbounded
    one is a denial of service on adversarial input.

Never introduces U+FFFD: every decode is strict, and a failed candidate is
discarded rather than replaced.
"""

import hashlib
import json
import re
import sys

MAX_PASSES = 3
# The non-ASCII characters each legacy codec can represent -- computed, not
# typed, because a hand-written list of cp1252's 27 punctuation characters is
# how the five undefined bytes get forgotten.
CP1252_HIGH = "".join(
    bytes([byte]).decode("cp1252", errors="ignore") for byte in range(0x80, 0x100)
)
LATIN1_HIGH = bytes(range(0x80, 0x100)).decode("latin-1")
CANDIDATE = re.compile(f"[{re.escape(''.join(sorted(set(CP1252_HIGH + LATIN1_HIGH))))}]+")


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def unmangle(fragment: str) -> str | None:
    """The UTF-8 text this fragment was before a legacy codec mangled it, or None.

    Returns None unless the round trip is provably the inverse: the fragment
    re-encodes without loss and those exact bytes are valid UTF-8.
    """
    for legacy in ("cp1252", "latin-1"):
        try:
            raw = fragment.encode(legacy)
        except UnicodeEncodeError:
            continue
        try:
            repaired = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if repaired != fragment:
            return repaired
    return None


def repair_once(text: str) -> tuple[str, int]:
    """One pass. Returns the text and how many runs it changed."""
    whole = unmangle(text)
    if whole is not None:
        return whole, 1
    repaired = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal repaired
        candidate = unmangle(match.group(0))
        if candidate is None:
            return match.group(0)
        repaired += 1
        return candidate

    return CANDIDATE.sub(replace, text), repaired


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    with open(source, "rb") as handle:
        raw = handle.read()

    notes: list[str] = []
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
        notes.append("removed a utf-8 byte order mark; it is not part of the text")
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        # Not UTF-8 at all. That is a different fault with the same symptom,
        # and transcoding it is the honest repair -- but say which codec was
        # assumed, because for bytes >= 0xa0 the file cannot tell you.
        encoding = (
            "latin-1" if any(byte in (0x81, 0x8D, 0x8F, 0x90, 0x9D) for byte in raw) else "cp1252"
        )
        text = raw.decode(encoding)
        notes.append(
            f"the input is not utf-8; it was read as {encoding} and transcoded. "
            "Run encoding_detect first if that guess matters"
        )

    original = text
    passes = 0
    runs = 0
    for _ in range(MAX_PASSES):
        candidate, changed = repair_once(text)
        if not changed:
            break
        text, passes, runs = candidate, passes + 1, runs + changed
    if passes == MAX_PASSES:
        notes.append(
            f"stopped at the {MAX_PASSES}-pass ceiling; text this deeply mangled may still "
            "contain mojibake, and an unbounded loop is a denial of service"
        )
    if passes and encoding == "utf-8":
        notes.append(
            f"repaired {runs} run(s) in {passes} pass(es); every run was re-encoded to a "
            "legacy codec and decoded as valid utf-8, so each change is provably reversible"
        )
    if not passes:
        notes.append("no run re-encodes to valid utf-8, so nothing here is mojibake")

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write(text)
    with open(target, "rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    finish(
        bom_removed=bom,
        changed=text != original or bom or encoding != "utf-8",
        characters_after=len(text),
        characters_before=len(original),
        encoding=encoding,
        notes=sorted(notes),
        output=target,
        passes=passes,
        repaired_runs=runs,
        sha256=digest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
