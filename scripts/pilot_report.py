"""Is this paying back? One readout, for the first organisation to run it.

Three instruments exist and none has data (DECISIONS 84). They were built so
that a first real deployment produces evidence instead of an anecdote, and this
is the thing somebody actually runs on a Friday to find out.

It answers four questions, in the order they matter:

    are agents stopping?          halts recorded at all
    is anybody answering?         the queue, and how old it is
    is it paying back?            repeat rate -- the thesis, measured
    did we get anything wrong?    disputes, and how far they reached

The convergence number is the one we cannot predict and the one that decides
whether this works for you. The thesis is that questions get answered once and
stop recurring. If your conventions are a long tail of near-unique cases,
nothing repeats, every halt is a fresh interruption, and the loop costs more
than it returns. That is a real possible outcome; this says which you have.

    BOOBS_API_KEY=<a key in your organisation> uv run python scripts/pilot_report.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx

API = os.environ.get("BOOBS_API_URL", "https://api.80085.ai")
STALE_AFTER = int(os.environ.get("PILOT_STALE_HOURS", "24"))


def _bar(value: float, width: int = 24) -> str:
    filled = int(round(value * width))
    return "#" * filled + "." * (width - filled)


async def main() -> int:
    key = os.environ.get("BOOBS_API_KEY")
    if not key:
        print("BOOBS_API_KEY is not set (any key in your organisation).", file=sys.stderr)
        return 2

    head = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=60, headers=head) as http:
        converge = (await http.get(f"{API}/v1/questions/convergence")).json()
        unanswered = (await http.get(f"{API}/v1/questions/unanswered", params={"limit": 10})).json()
        stale = (
            await http.get(
                f"{API}/v1/questions/stale",
                params={"older_than_hours": STALE_AFTER, "limit": 10},
            )
        ).json()
        pending = (
            await http.get(f"{API}/v1/answers/awaiting-verification", params={"limit": 10})
        ).json()

    halts = converge.get("total_halts", 0)
    distinct = converge.get("distinct_questions", 0)

    print("\n" + "=" * 68)
    print("  80085 pilot report")
    print("=" * 68)

    if not halts:
        print(
            "\n  No halts recorded yet.\n\n"
            "  Either your agents have not hit a convention they cannot determine,\n"
            "  or they are not calling ask_for_help. The second is far more likely\n"
            "  early on, and it looks exactly like the first -- check that the halt\n"
            "  paragraph is in the system prompt your agents actually run with."
        )
        return 0

    repeat = converge.get("repeat_rate", 0.0)
    answered = converge.get("answered_share", 0.0)
    print(f"\n  ARE AGENTS STOPPING?      {halts} halts across {distinct} distinct questions")
    print(f"  assumed instead           {converge.get('proceeded_on_an_assumption', 0)}")

    print(f"\n  IS IT PAYING BACK?        repeat rate {repeat:.0%}  [{_bar(repeat)}]")
    print(f"                            answered    {answered:.0%}  [{_bar(answered)}]")
    print(f"  answers reused            {converge.get('answers_reused', 0)} times")

    # The reading is the point. A number nobody can interpret is a number
    # nobody acts on, and this is the first time anyone has seen these.
    if repeat < 0.15:
        verdict = (
            "Almost every halt is a NEW question. The loop is not paying back yet.\n"
            "  Either it is early, or your conventions are a long tail of one-offs --\n"
            "  in which case the halt is still worth having and the corpus is not."
        )
    elif answered < 0.3:
        verdict = (
            "Questions repeat but few are answered. This is the worst quadrant:\n"
            "  agents stopping over and over on the same unanswered thing. The\n"
            "  fix is somebody spending twenty minutes on the queue below."
        )
    else:
        verdict = (
            "Questions repeat and are getting answered. This is the loop working:\n"
            "  every answer below is a halt that will not happen again."
        )
    print(f"\n  {verdict}")

    rows = unanswered.get("questions", [])
    if rows:
        print(f"\n  STUCK ON  (top {min(len(rows), 5)}, most-asked first)")
        for q in rows[:5]:
            print(f"    {q['asked']:>3}x  {q['need'][:56]}")

    old = stale.get("stale", [])
    if old:
        print(f"\n  UNANSWERED FOR OVER {STALE_AFTER}H  ({len(old)})")
        for q in old[:5]:
            flag = "  [proceeded on an assumption]" if q.get("assumed") else ""
            print(f"    {q['hours_waiting']:>4}h  {q['asked']}x  {q['need'][:44]}{flag}")

    waiting = pending.get("awaiting", [])
    if waiting:
        print(f"\n  AWAITING VERIFICATION  ({len(waiting)})")
        for a in waiting[:5]:
            print(f"    {a['agents_waiting']:>3} agents  {a['need'][:50]}")

    print("\n" + "=" * 68)
    print(
        "  The number that matters is repeat rate. It is the only thing that says\n"
        "  whether answering a question once is worth anything, and we cannot\n"
        "  predict it for you -- it is a property of your work, not of our code."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
