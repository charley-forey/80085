"""A caller must not get 2x a window's budget by hitting a window boundary.

`limits.py` counts hits in a fixed window stored as one row per caller per
window. Counting only the current window's row lets a caller spend the full
budget right before a boundary and the full budget again right after --
twice the configured limit inside one `seconds`-wide slice of real time.
`weighted_hits` is the pure arithmetic `Window.check` uses to fold the
previous window's row into that count, weighted by how much of it the
current window has not yet overtaken, so the fixed-window row still produces
a sliding-window answer.
"""

from __future__ import annotations

from boobs_api.limits import weighted_hits


def test_a_full_previous_window_counts_in_full_at_the_boundary() -> None:
    """Right at the boundary, nothing has elapsed: the old window's hits are
    exactly as real as if they had just happened, so they count in full."""
    assert weighted_hits(current=0, previous=10, elapsed_fraction=0.0) == 10


def test_a_caller_cannot_refill_the_same_budget_by_waiting_for_the_boundary() -> None:
    """The failure a fixed window has: 10 hits late in one window plus 10 more
    right after the boundary is 20 inside a thin slice of real time, but a
    fixed window only ever sees the 10 in whichever window it is asked about.
    The sliding estimate catches it instead."""
    limit = 10
    assert weighted_hits(current=10, previous=10, elapsed_fraction=0.0) > limit


def test_the_previous_window_fades_out_as_the_current_one_fills() -> None:
    """Halfway into the current window, the previous one should count for
    about half of what it would at the boundary."""
    assert weighted_hits(current=0, previous=10, elapsed_fraction=0.5) == 5


def test_the_previous_window_stops_counting_once_it_has_fully_elapsed() -> None:
    assert weighted_hits(current=0, previous=10, elapsed_fraction=1.0) == 0


def test_elapsed_fraction_is_clamped_so_a_clock_edge_cannot_go_negative() -> None:
    """`check` computes elapsed_fraction from two separate calls to
    `time.time()`, so it can land fractionally outside [0, 1] right at an
    edge. The weight must not go negative or above the previous window's
    full count because of that."""
    assert weighted_hits(current=0, previous=10, elapsed_fraction=1.2) == 0
    assert weighted_hits(current=0, previous=10, elapsed_fraction=-0.1) == 10
