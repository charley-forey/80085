"""Split an amount of money into shares that add back up to exactly the amount.

argv: <input file>   ->  result.json

Input is JSON:
  {"total": "100.00", "weights": [1, 1, 1], "currency": "USD"}
  {"total": "1000", "weights": ["2", "1"], "exponent": 0}

Divide 100.00 three ways, round each share, and you have 99.99. Divide it in
the other direction and you have 100.01. Either way somebody's ledger does not
balance, and the fix is applied at the end of the quarter by hand.

The largest-remainder method fixes it by construction: every share is floored
to the currency's smallest unit, the units left over are handed out one each
to the shares with the largest fractional parts, and the total is therefore
exact rather than approximately right. The invariant is asserted before the
result is written -- a run that cannot make the parts sum to the whole exits
non-zero instead of reporting a number that does not add up.

What this encodes beyond the method itself:

  * **money is integers.** Everything happens in minor units as `Decimal`, and
    no float appears anywhere. `0.1 + 0.2 != 0.3` in binary, and a total built
    from floats drifts by a cent every few thousand rows.
  * **not every currency has two decimal places.** JPY and KRW have none, and
    dividing 1000 yen as though it were 10.00 yen loses two orders of
    magnitude; KWD, BHD and OMR have three, and rounding to two gives away
    ten times the intended rounding. The exponent comes from the currency
    code, and can be overridden explicitly.
  * **ties must break the same way every run.** Equal remainders are resolved
    by position, so the extra cent always lands on the earliest share.
    Distributing it by iteration order over a dict, or by a sort that is not
    total, makes an allocation that changes between runs -- which is a
    reconciliation failure that reproduces only sometimes.
  * **negatives allocate on the magnitude**, so a refund of -100.00 splits as
    -33.34/-33.33/-33.33 rather than rounding towards zero and losing a unit.
  * a total with more precision than the currency has is refused rather than
    rounded, because silently rounding the input is how the discrepancy this
    capability exists to prevent gets in one step earlier.
"""

import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation

# ISO 4217 minor units that are not 2. Everything absent from this table has 2,
# which is the assumption that is wrong often enough to be worth naming.
EXPONENTS = {
    "BHD": 3,
    "BIF": 0,
    "CLF": 4,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "IQD": 3,
    "ISK": 0,
    "JOD": 3,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "PYG": 0,
    "RWF": 0,
    "TND": 3,
    "UGX": 0,
    "UYW": 4,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
}
MAX_SHARES = 10_000


def finish(**fields: object) -> None:
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(fields, out, indent=2, sort_keys=True)
        out.write("\n")


def main() -> int:
    with open(sys.argv[1], "rb") as handle:
        raw = handle.read()
    request = json.loads(raw.decode("utf-8"))
    currency = request.get("currency")
    exponent = int(request["exponent"]) if "exponent" in request else EXPONENTS.get(currency, 2)
    if not 0 <= exponent <= 6:
        print("exponent must be between 0 and 6", file=sys.stderr)
        return 2
    try:
        total = Decimal(str(request["total"]))
        weights = [Decimal(str(weight)) for weight in request["weights"]]
    except InvalidOperation:
        print("total and weights must be exact decimal strings, never floats", file=sys.stderr)
        return 2
    if not weights or len(weights) > MAX_SHARES:
        print(f"between 1 and {MAX_SHARES} weights", file=sys.stderr)
        return 2
    if any(weight < 0 for weight in weights):
        print("weights cannot be negative", file=sys.stderr)
        return 2
    weight_total = sum(weights)
    if weight_total == 0:
        print("the weights sum to zero, so there is no share to allocate by", file=sys.stderr)
        return 2

    scaled = total.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        print(
            f"{total} has more precision than {currency or 'this currency'} has minor units "
            f"(10^-{exponent}); rounding the input here is how the discrepancy starts",
            file=sys.stderr,
        )
        return 2
    units = int(scaled)
    sign = -1 if units < 0 else 1
    magnitude = abs(units)

    # Floor every share, then hand the leftover units to the largest remainders.
    exact = [magnitude * weight / weight_total for weight in weights]
    floors = [int(share.to_integral_value(rounding="ROUND_FLOOR")) for share in exact]
    remainder = magnitude - sum(floors)
    # Sorted by remainder descending and index ascending: a total order, so the
    # same input always produces the same allocation.
    order = sorted(range(len(weights)), key=lambda index: (-(exact[index] - floors[index]), index))
    for index in order[:remainder]:
        floors[index] += 1

    allocations = [Decimal(sign * amount).scaleb(-exponent) for amount in floors]
    quantum = Decimal(1).scaleb(-exponent)
    rendered = [str(amount.quantize(quantum)) for amount in allocations]
    # The whole point of the exercise. If this ever fails, the run must not
    # produce a result file that somebody reconciles against.
    assert sum(allocations) == total, f"{sum(allocations)} != {total}"

    finish(
        currency=currency,
        exponent=exponent,
        total=str(total.quantize(quantum)),
        weights=[str(weight) for weight in weights],
        allocations=rendered,
        sum=str(sum(allocations).quantize(quantum)),
        exact=True,
        method="largest remainder, ties to the earliest share",
        redistributed_units=remainder,
        minor_units=units,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
