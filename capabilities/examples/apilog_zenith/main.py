"""Count genuine failures in a Zenith internal gateway access log.

The gateway does not use HTTP status codes the way the internet does, and the
log does not say so:

    299 IS A SUCCESS.        "Accepted and queued" -- non-standard, and the
                             single most common code in the file.
    A RETRYABLE 4xx IS NOT   The client is told to back off; the gateway
    A FAILURE.               retried and the request completed elsewhere.
    A 5xx ALWAYS IS.         Even when flagged retryable.

Anyone counting `status >= 300` gets a number that is plausible, defensible and
wrong, and every dashboard built on it is wrong in the same direction.

Reads input.txt from the working directory, writes result.json.
"""

from __future__ import annotations

import json
from pathlib import Path

QUEUED_OK = 299


def audit(text: str) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        _, endpoint, status_text, retryable_text = parts
        status, retryable = int(status_text), retryable_text == "1"
        if status < 300 or status == QUEUED_OK:
            failed = False
        elif status >= 500:
            failed = True  # a 5xx is ours, retryable or not
        else:
            failed = not retryable  # a retryable 4xx completed on a later hop
        rows.append(
            {"endpoint": endpoint, "status": status, "retryable": retryable, "failed": failed}
        )
    return {
        "format": "ZENITH-GW-LOG-V4",
        "failed_requests": sum(1 for r in rows if r["failed"]),
        "request_count": len(rows),
        "queued_accepted": sum(1 for r in rows if r["status"] == QUEUED_OK),
        "rows": rows,
    }


def main() -> None:
    text = Path("input.txt").read_text(encoding="utf-8")
    with open("result.json", "w", encoding="utf-8", newline="\n") as out:
        json.dump(audit(text), out, indent=2, sort_keys=True)
        out.write("\n")


if __name__ == "__main__":
    main()
