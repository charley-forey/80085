"""Sliding-window weighting for rate limits.

Fixed windows let a caller at a boundary spend a window's worth of hits
twice in quick succession -- once just before the boundary, once just after.
`weighted_hits` is the pure arithmetic that closes that gap: the previous
window's count decays linearly over the current one instead of vanishing the
instant the clock ticks over.
"""

from __future__ import annotations

from boobs_api.limits import weighted_hits


def test_the_previous_window_decays_instead_of_vanishing_at_the_boundary() -> None:
    limit = 10
    filled_previous_window = 10

    # An instant after the boundary, a caller who just filled the previous
    # window is still charged for nearly all of it -- the straddle the
    # ponytail comment named no longer buys a second full window for free.
    just_after = weighted_hits(
        hits=1, previous=filled_previous_window, window_start=100, seconds=60, now=100.1
    )
    assert just_after > limit

    # Halfway through the current window, the previous one counts for half.
    assert weighted_hits(hits=0, previous=10, window_start=100, seconds=60, now=130) == 5

    # Right before the window closes, the previous window barely counts.
    just_before_close = weighted_hits(
        hits=0, previous=filled_previous_window, window_start=100, seconds=60, now=159.9
    )
    assert just_before_close < 0.2

    # With no previous window, only the current count matters.
    assert weighted_hits(hits=3, previous=0, window_start=100, seconds=60, now=142) == 3
