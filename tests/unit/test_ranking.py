"""Ranking answers "will this work for me", not "is this text similar"."""

from __future__ import annotations

from datetime import timedelta

import pytest

from boobs_common.clock import now
from boobs_domain.enums import Compatibility, Recommendation, VerificationLevel
from boobs_retrieval import ranking


def signals(**overrides: object) -> ranking.Signals:
    """A healthy Experience: relevant, fast, fresh, and -- since evidence now
    means corroborated evidence -- proven by more than one organization."""
    base: dict[str, object] = {
        "relevance": 1.0,
        "compatibility": Compatibility.HIGH,
        "successful_runs": 100,
        "failed_runs": 1,
        "last_verified_at": now(),
        "median_duration_ms": 1000,
        "requires_network": False,
        "distinct_organizations": 2,
        "verification_level": VerificationLevel.PROVEN,
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
    incompatible = signals(compatibility=Compatibility.NONE)
    assert ranking.recommend(0.99, incompatible) is Recommendation.AVOID


def test_proven_and_relevant_is_recommended() -> None:
    proven = signals()
    final, _ = ranking.score(proven)
    assert ranking.recommend(final, proven) is Recommendation.USE


def test_unproven_experience_is_not_recommended_for_use() -> None:
    unproven = signals(
        successful_runs=0,
        failed_runs=0,
        last_verified_at=None,
        distinct_organizations=0,
        verification_level=VerificationLevel.UNVERIFIED,
    )
    final, _ = ranking.score(unproven)
    assert ranking.recommend(final, unproven) is not Recommendation.USE


def test_one_organization_cannot_recommend_its_own_experience() -> None:
    """The T1 attack: mint an org, run a trivially-passing artifact until the
    counters look good. Runs are capped per organization and "use" is gated on
    corroboration, so no amount of self-running gets there."""
    alone = signals(successful_runs=10_000, failed_runs=0, distinct_organizations=1)
    final, _ = ranking.score(alone)
    assert ranking.recommend(final, alone) is Recommendation.CONSIDER

    corroborated = signals(successful_runs=10_000, failed_runs=0, distinct_organizations=2)
    final, _ = ranking.score(corroborated)
    assert ranking.recommend(final, corroborated) is Recommendation.USE


def test_runs_by_one_organization_saturate() -> None:
    """Ten runs and ten thousand runs from a single org are the same evidence:
    it is one actor's observation, repeated."""
    assert ranking.corroborated_successes(10_000, 1) == ranking.RUNS_PER_ORGANIZATION_CAP
    assert ranking.corroborated_successes(10_000, 3) == 3 * ranking.RUNS_PER_ORGANIZATION_CAP
    # Never inflates a real count.
    assert ranking.corroborated_successes(4, 9) == 4


def test_a_weak_verifier_earns_less_confidence_than_a_strong_one() -> None:
    """T7: `exit 0` is chosen by the artifact; a sha256 match is not. Identical
    run counts must not produce identical confidence."""
    counts = {"successful_runs": 40, "failed_runs": 0, "distinct_organizations": 4}
    weak = ranking.confidence_score(**counts, verification_level=VerificationLevel.CLAIMED)
    strong = ranking.confidence_score(**counts, verification_level=VerificationLevel.PROVEN)
    assert 0.0 < weak < strong

    weak_signals = signals(**counts, verification_level=VerificationLevel.CLAIMED)
    strong_signals = signals(**counts, verification_level=VerificationLevel.PROVEN)
    assert ranking.score(weak_signals)[0] < ranking.score(strong_signals)[0]


def test_nothing_proven_is_no_confidence() -> None:
    """A version whose verifier has never passed has no evidence, whatever the
    executions table says happened."""
    assert ranking.confidence_score(50, 0, 5, VerificationLevel.UNVERIFIED) == 0.0


def test_corroboration_is_not_usage() -> None:
    """Same number of runs, more organizations behind them: better evidence."""
    narrow, _ = ranking.score(signals(successful_runs=30, failed_runs=0, distinct_organizations=1))
    broad, _ = ranking.score(signals(successful_runs=30, failed_runs=0, distinct_organizations=3))
    assert broad > narrow


def test_rrf_rewards_agreement_between_retrievers() -> None:
    fused = ranking.reciprocal_rank_fusion([["a", "b", "c"], ["c", "a", "b"]])
    assert max(fused, key=lambda key: fused[key]) == "a"


def test_only_the_best_lexical_hit_is_perfectly_relevant() -> None:
    """A verbatim goal statement must not tie with its neighbours.

    ts_rank_cd for any decent hit exceeds LEXICAL_SCALE, and a fixed divisor
    clamped all of them to 1.0: the exact match ranked twelfth among ties.
    """
    best, near, weak = 0.6, 0.36, 0.05
    assert ranking.relevance_of(best, None, best) == 1.0
    assert ranking.relevance_of(near, None, best) == 0.6
    assert ranking.relevance_of(near, None, best) < ranking.relevance_of(best, None, best)
    # A query too weak to reach the scale keeps the fixed divisor, so a lone
    # poor hit is not promoted to a perfect one.
    assert ranking.relevance_of(weak, None, weak) == weak / ranking.LEXICAL_SCALE
    # The semantic retriever still gets the last word when it is stronger.
    assert ranking.relevance_of(near, 0.9, best) == 0.9


def test_a_different_conversion_is_a_different_job() -> None:
    """csv_to_json and csv_to_jsonl are not interchangeable.

    In production a JSONL query returned twelve JSON-array Experiences above
    the JSONL one: wording that close saturates relevance at 1.0, so the exact
    match tied and then lost the tie to whichever neighbour had been run most.
    A bonus cannot separate candidates that are already at the cap; only
    lowering the mismatched ones can.
    """
    assert ranking.intent_relevance(0.95, "csv_to_jsonl", "csv_to_jsonl") == 1.0
    mismatched = ranking.intent_relevance(1.0, "csv_to_jsonl", "csv_to_json")
    assert mismatched == ranking.INTENT_MISMATCH_FACTOR
    assert mismatched < ranking.intent_relevance(0.95, "csv_to_jsonl", "csv_to_jsonl")


def test_a_vague_query_penalizes_nothing() -> None:
    """Only two *specific* conversions can disagree. A query that named no
    direction has said nothing to disagree with, and an Experience recorded
    without one must not be pushed down for it."""
    assert ranking.intent_relevance(0.9, "unknown", "csv_to_json") == 0.9
    assert ranking.intent_relevance(0.9, "csv_to_json", "unknown") == 0.9
    assert ranking.intent_relevance(0.9, "validate_json", "csv_to_json") == 0.9


def test_only_the_output_format_makes_two_conversions_disagree() -> None:
    """A different source is routinely the same bytes; a different target is not.

    Penalising every difference made non-conversions immune to the penalty and
    so relatively cheaper: "convert a spreadsheet export to json" returned a
    JSON merge patch above the CSV-to-JSON converter, because merge_json is
    not a conversion and escaped a discount its rival took.
    """
    # Same output, different input: a spreadsheet export IS a CSV file.
    assert ranking.intent_relevance(0.9, "xlsx_to_json", "csv_to_json") == 0.9
    # Different output: not interchangeable, whatever went in.
    assert ranking.intent_relevance(1.0, "csv_to_jsonl", "csv_to_json") == pytest.approx(
        ranking.INTENT_MISMATCH_FACTOR
    )
    assert ranking.intent_relevance(1.0, "csv_to_json", "json_to_csv") == pytest.approx(
        ranking.INTENT_MISMATCH_FACTOR
    )
    # A non-conversion is neither rewarded nor punished by this rule.
    assert ranking.intent_relevance(0.9, "csv_to_json", "merge_json") == 0.9
