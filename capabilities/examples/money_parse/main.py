"""Parse money written by humans in any locale, exactly, and flag what has two readings.

argv: <input file>   ->  result.json

Input is JSON: {"values": ["1.234,56", "(1,234.56)", ...], "hint": "none"|"us"|"eu"}

`1,234` is one thousand two hundred and thirty four in Chicago and one point
two three four in Cologne. Nothing in the string says which. A parser that
picks one is wrong by a factor of a thousand on the other locale's data, and
because both readings are valid numbers nothing downstream ever notices.

Everything here is `Decimal` from the first character. `float("0.1") +
float("0.2")` is not `float("0.3")`, and a total assembled from binary floats
drifts by a cent per few thousand rows -- which reconciles as "rounding" until
an auditor asks.

The rules, which are the actual content of this capability:

  * **both separators present: the last one is the decimal point.** `1.234,56`
    is European, `1,234.56` is American, and no other reading of either is
    consistent.
  * **one separator, three digits after it: ambiguous.** Reported with both
    values and no answer unless `hint` says which locale the file came from.
  * **one separator, not three digits after it: it is the decimal point.**
    `1,5` and `1.2345` have only one reading.
  * **one separator appearing more than once: grouping.** `1.234.567` is an
    integer; there is no number with two decimal points.
  * **Indian grouping is 2-2-3**, so `1,23,456.78` is 123456.78 and a
    group-of-three validator rejects a perfectly good number.
  * **negatives come in three shapes**: a leading minus, a trailing minus
    (SAP and mainframe exports), and parentheses (accounting). A parser that
    only knows the first turns a credit into a debit.
  * **the group separator may be a space** -- and in French output it is
    usually U+00A0 or U+202F, which is not the space on your keyboard and does
    not match `\\s` in every language's regex engine.
  * **scale is preserved**: `1.50` stays two decimal places, because dropping
    to `1.5` loses the statement that this is a cent-precise figure.
  * a currency symbol is recorded, never trusted for format: `$` is used by a
    dozen countries and several of them write `1.234,56`.
"""

import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation

SPACES = {chr(point): " " for point in (0xA0, 0x2007, 0x2009, 0x202F, 0x2005, 0x2008)}
# Single characters only: a multi-character marker like "kr" would strip the
# letters out of the middle of anything else it appeared in.
SYMBOLS = "$€£¥₹₽₺₩¢"
CODE = re.compile(r"^([A-Z]{3})\s*|\s*([A-Z]{3})$")
DIGITS = re.compile(r"^\d+$")


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def grouping(digits: str, separator: str, count: int) -> str | None:
    """How the whole part is grouped, or None if it is not grouped legally."""
    parts = digits.split(separator)
    if count == 0:
        return "none"
    if len(parts[0]) > 3 or any(len(part) != 3 for part in parts[1:]):
        # Indian: the last group is three and every earlier one is two.
        if len(parts) > 1 and len(parts[-1]) == 3 and all(len(p) == 2 for p in parts[1:-1]):
            return "indian" if 1 <= len(parts[0]) <= 2 else None
        return None
    return "three"


def as_decimal(whole: str, fraction: str, negative: bool) -> Decimal:
    text = f"{'-' if negative else ''}{whole or '0'}" + (f".{fraction}" if fraction else "")
    return Decimal(text)


def interpret(value: str, hint: str) -> dict[str, object]:
    notes: list[str] = []
    text = value
    for space, plain in SPACES.items():
        if space in text:
            notes.append(
                "the group separator is a no-break or thin space, not U+0020: a strip() or a "
                "split on ' ' leaves it in place and the value then fails to parse"
            )
            text = text.replace(space, plain)
    text = text.strip()

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
        notes.append(
            "parentheses are an accounting negative; read as a positive this is a sign error"
        )
    currency = None
    match = CODE.search(text)
    if match:
        currency = match.group(1) or match.group(2)
        text = CODE.sub("", text).strip()
    for symbol in SYMBOLS:
        if symbol in text:
            currency = currency or symbol
            text = text.replace(symbol, "").strip()
    if text.endswith("-"):
        negative = True
        text = text[:-1].strip()
        notes.append(
            "a trailing minus is a negative; mainframe and SAP exports write them this way"
        )
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()
    if text.startswith("+"):
        text = text[1:].strip()
    if " " in text:
        # A space only ever groups -- no convention uses one as a decimal point --
        # so removing it also removes an ambiguity that a comma would have had.
        notes.append("spaces group the digits; '1 234' has only one reading, unlike '1,234'")
        text = text.replace(" ", "")

    if not text or not re.fullmatch(r"[0-9.,]+", text):
        return {
            "input": value,
            "value": None,
            "scale": None,
            "negative": negative,
            "currency": currency,
            "ambiguous": False,
            "interpretations": [],
            "reason": "not a number once the currency and sign were removed",
            "notes": sorted(notes),
        }

    dots, commas = text.count("."), text.count(",")
    readings: list[dict[str, str]] = []
    try:
        if dots and commas:
            # The rightmost separator is the decimal point; the other must be a
            # legal grouping, or the string is not a number at all.
            decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
            group_sep = "," if decimal_sep == "." else "."
            whole, _, fraction = text.rpartition(decimal_sep)
            if not DIGITS.match(fraction) or decimal_sep in whole:
                raise InvalidOperation
            style = grouping(whole, group_sep, whole.count(group_sep))
            if style is None:
                raise InvalidOperation
            if style == "indian":
                notes.append(
                    "grouped 2-2-3, which is the Indian convention: a validator that insists on "
                    "groups of three rejects this number"
                )
            readings.append(
                {
                    "style": "eu" if decimal_sep == "," else "us",
                    "value": str(as_decimal(whole.replace(group_sep, ""), fraction, negative)),
                }
            )
        elif dots + commas == 0:
            readings.append({"style": "plain", "value": str(as_decimal(text, "", negative))})
        else:
            separator = "." if dots else ","
            other = "," if dots else "."
            count = dots + commas
            whole, _, tail = text.rpartition(separator)
            if not DIGITS.match(tail) or not DIGITS.match(whole.replace(separator, "")):
                raise InvalidOperation
            if count > 1:
                if grouping(text, separator, count) is None:
                    raise InvalidOperation
                readings.append(
                    {
                        "style": "grouped",
                        "value": str(as_decimal(text.replace(separator, ""), "", negative)),
                    }
                )
                notes.append(
                    f"'{separator}' appears {count} times, so it groups rather than separates "
                    "decimals; no number has two decimal points"
                )
            elif len(tail) == 3 and whole:
                # The genuinely undecidable case, and the reason this capability exists.
                readings.append(
                    {
                        "style": "us" if separator == "," else "eu",
                        "value": str(as_decimal(whole + tail, "", negative)),
                    }
                )
                readings.append(
                    {
                        "style": "eu" if separator == "," else "us",
                        "value": str(as_decimal(whole, tail, negative)),
                    }
                )
                notes.append(
                    f"'{separator}' with exactly three digits after it is a thousands separator "
                    "in one convention and a decimal point in the other; the value has two "
                    f"readings that differ by 1000x, and '{other}' does not appear to settle it"
                )
            else:
                readings.append(
                    {
                        "style": "eu" if separator == "," else "us",
                        "value": str(as_decimal(whole, tail, negative)),
                    }
                )
    except (InvalidOperation, ValueError):
        return {
            "input": value,
            "value": None,
            "scale": None,
            "negative": negative,
            "currency": currency,
            "ambiguous": False,
            "interpretations": [],
            "reason": "the separators are not a legal grouping in either convention",
            "notes": sorted(notes),
        }

    chosen: dict[str, str] | None = readings[0] if len(readings) == 1 else None
    ambiguous = len(readings) > 1
    if ambiguous and hint != "none":
        chosen = next((reading for reading in readings if reading["style"] == hint), None)
        if chosen is not None:
            ambiguous = False
            notes.append(
                f"resolved by hint={hint}, which is the caller's knowledge of where the file "
                "came from and not evidence from the value"
            )
    amount = Decimal(chosen["value"]) if chosen else None
    return {
        "input": value,
        "value": str(amount) if amount is not None else None,
        "scale": -amount.as_tuple().exponent if amount is not None else None,
        "negative": negative,
        "currency": currency,
        "ambiguous": ambiguous,
        "interpretations": readings,
        "reason": "two readings differing by 1000x" if ambiguous else None,
        "notes": sorted(notes),
    }


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    hint = request.get("hint", "none")
    if hint not in {"none", "us", "eu"}:
        print("hint must be none, us or eu", file=sys.stderr)
        return 2
    results = [interpret(str(value), hint) for value in request["values"]]
    finish(
        hint=hint,
        count=len(results),
        ambiguous_count=sum(1 for item in results if item["ambiguous"]),
        unparsed_count=sum(1 for item in results if not item["interpretations"]),
        values=results,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
