"""The weighted window: a caller cannot get up to 2x a limit by hitting it
once on each side of a boundary, which a fixed window could not stop (see
`boobs_api.limits`).
"""

from __future__ import annotations

from boobs_api.limits import _weighted_count


def test_weighted_count_decays_linearly_across_the_boundary() -> None:
    # At the boundary itself, the previous window counts in full.
    assert _weighted_count(hits=0, previous_hits=10, elapsed_fraction=0.0) == 10
    # Halfway into the current window, only half of it still counts.
    assert _weighted_count(hits=0, previous_hits=10, elapsed_fraction=0.5) == 5
    # A full window after the boundary, none of it counts -- the fixed-window
    # behaviour this replaces.
    assert _weighted_count(hits=0, previous_hits=10, elapsed_fraction=1.0) == 0
    # Current-window hits are never discounted, whatever the previous window did.
    assert _weighted_count(hits=4, previous_hits=10, elapsed_fraction=0.5) == 9
    # Clamped: float error or a clock either side of the boundary cannot carry
    # more, or less, than one full window's worth of weight.
    assert _weighted_count(hits=0, previous_hits=10, elapsed_fraction=-0.1) == 10
    assert _weighted_count(hits=0, previous_hits=10, elapsed_fraction=1.1) == 0
