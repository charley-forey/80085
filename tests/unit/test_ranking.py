"""Ranking answers "will this work for me", not "is this text similar"."""

from __future__ import annotations

from datetime import timedelta

from boobs_common.clock import now
from boobs_domain.enums import Compatibility, Recommendation
from boobs_retrieval import ranking


def signals(**overrides: object) -> ranking.Signals:
    base: dict[str, object] = {
        "relevance": 1.0,
        "compatibility": Compatibility.HIGH,
        "successful_runs": 100,
        "failed_runs": 1,
        "last_verified_at": now(),
        "median_duration_ms": 1000,
        "requires_network": False,
    }
    base.update(overrides)
    return ranking.Signals(**base)  # type: ignore[arg-type]


def test_one_lucky_run_is_not_confidence() -> None:
    """The whole point of Wilson: a 1/1 record is not 100% trustworthy."""
    assert ranking.wilson_lower_bound(1, 0) < 0.3
    assert ranking.wilson_lower_bound(1000, 0) > 0.99


def test_more_evidence_beats_less_at_the_same_rate() -> None:
    thin, _ = ranking.score(signals(successful_runs=3, failed_runs=0))
    thick, _ = ranking.score(signals(successful_runs=300, failed_runs=0))
    assert thick > thin


def test_stale_evidence_ranks_below_fresh() -> None:
    fresh, _ = ranking.score(signals(last_verified_at=now()))
    stale, _ = ranking.score(signals(last_verified_at=now() - timedelta(days=200)))
    assert fresh > stale


def test_network_requirement_is_a_penalty() -> None:
    offline, _ = ranking.score(signals(requires_network=False))
    online, _ = ranking.score(signals(requires_network=True))
    assert offline > online


def test_incompatible_is_never_recommended() -> None:
    assert ranking.recommend(0.99, Compatibility.NONE) is Recommendation.AVOID


def test_proven_and_relevant_is_recommended() -> None:
    final, _ = ranking.score(signals())
    assert ranking.recommend(final, Compatibility.HIGH) is Recommendation.USE


def test_unproven_experience_is_not_recommended_for_use() -> None:
    final, _ = ranking.score(signals(successful_runs=0, failed_runs=0, last_verified_at=None))
    assert ranking.recommend(final, Compatibility.HIGH) is not Recommendation.USE


def test_rrf_rewards_agreement_between_retrievers() -> None:
    fused = ranking.reciprocal_rank_fusion([["a", "b", "c"], ["c", "a", "b"]])
    assert max(fused, key=lambda key: fused[key]) == "a"
