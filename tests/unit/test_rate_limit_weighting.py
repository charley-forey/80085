"""`Window.check`'s sliding-window weighting, tested as pure math -- no
Postgres needed to check the arithmetic that fades the previous window out.
"""

from __future__ import annotations

from boobs_api.limits import _weighted_count


def test_previous_window_counts_in_full_at_the_very_start() -> None:
    assert _weighted_count(current_hits=0, previous_hits=10, elapsed_fraction=0.0) == 10


def test_previous_window_has_faded_out_by_the_very_end() -> None:
    assert _weighted_count(current_hits=3, previous_hits=10, elapsed_fraction=1.0) == 3


def test_previous_window_is_weighted_partway_through() -> None:
    assert _weighted_count(current_hits=2, previous_hits=10, elapsed_fraction=0.5) == 7
