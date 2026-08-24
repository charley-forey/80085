"""Ranking (spec section 12).

All ranking weights live in this file. If a recall result looks wrong, this is
the only place to look.

The question being scored is not "which text is most similar" but "which of
these will most probably work for the agent asking, right now".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from boobs_common.clock import now
from boobs_common.config import settings
from boobs_domain.enums import Compatibility, Recommendation, VerificationLevel

# Quality weights. These describe how *good* a match is once we already know
# it is the right kind of thing; relevance is applied separately, as a gate.
QUALITY_WEIGHTS: dict[str, float] = {
    "compatibility": 0.30,
    "confidence": 0.34,
    "usage": 0.10,
    "corroboration": 0.07,
    "recency": 0.12,
    "latency": 0.05,
    "risk": 0.02,
}

# How much a verdict is worth, by the strongest verifier that has passed.
# A trivial `exit 0` and a byte-exact sha256 match are not the same claim, and
# ranking used to treat them as identical -- so an artifact author could earn
# full confidence from a verifier they themselves control the input to.
VERIFICATION_STRENGTH: dict[VerificationLevel, float] = {
    VerificationLevel.UNVERIFIED: 0.0,
    VerificationLevel.CLAIMED: 0.6,
    VerificationLevel.PROVEN: 1.0,
}

# The most successful runs one organization's evidence can be worth. Runs
# beyond this are free to manufacture: the same actor pressing the same button
# is one observation repeated, not many observations. Ten is deliberate --
# Wilson puts 10/0 at 72.2%, so a single organization alone tops out at
# "promising" and can never reach "yeah, run it" by itself.
RUNS_PER_ORGANIZATION_CAP = 10

# Breadth of corroboration saturates here: three independent organizations is
# as good as thirty for the purpose of believing the thing works at all.
CORROBORATION_SATURATION = 3.0

# How much of the final score a merely-relevant match can earn before any
# evidence exists. The remainder has to be earned by proven runs, which is why
# a brand new Experience reads as "consider", never "use".
RELEVANCE_FLOOR = 0.45

# Relevance counts superlinearly. Running the wrong capability is not a
# slightly worse outcome, it is a guaranteed failure -- so a clearly better
# match must beat a slightly-proven worse one. With a linear term, three
# successful runs of "CSV to JSON" outranked a perfect match for "JSON to CSV"
# by 0.011, and the agent got a capability that could not work.
RELEVANCE_EXPONENT = 2.0

# Lexical rank and cosine similarity are on different scales; ts_rank_cd
# saturates quickly, so it is squashed into [0, 1] before being compared.
LEXICAL_SCALE = 0.12

# Credit for an exact normalized-intent match. Applied to relevance, never to
# the final score: matching the task is not the same as being known to work.
INTENT_MATCH_BONUS = 0.15

# And the other half of that signal. Two intents that each name a source and a
# target, and disagree, are positive evidence of a different job -- csv_to_json
# produces an array, csv_to_jsonl produces a line per record, and an agent that
# asked for one cannot use the other. A bonus alone could not express this:
# relevance saturates at 1.0 for near-identical wording, so the exact match
# tied with a dozen neighbours and lost the tie to whichever had been run more.
# Only applied when both labels are specific, so a vague query penalizes
# nothing.
INTENT_MISMATCH_FACTOR = 0.8

# A run this recent counts as fully fresh; older evidence decays toward zero
# over STALE_AFTER_DAYS (spec section 24).
FRESH_HOURS = 24.0
STALE_AFTER_DAYS = 90.0

# Below this score an agent is better off solving the task itself.
# 0.70 is set so that a perfectly relevant but *unproven* Experience lands in
# 'consider', not 'use': relevance alone is not evidence.
USE_THRESHOLD = 0.70
CONSIDER_THRESHOLD = 0.40

# Below this, do not return the candidate at all. An empty answer is a correct
# answer; a confident wrong capability is not.
MIN_SCORE = 0.30


@dataclass(frozen=True)
class Signals:
    relevance: float
    compatibility: Compatibility
    successful_runs: int
    failed_runs: int
    last_verified_at: datetime | None
    median_duration_ms: int | None
    requires_network: bool
    required_capabilities: tuple[str, ...] = ()
    # How many organizations have independently proven this, and the strongest
    # verifier that ever passed. Both default to "no corroboration, nothing
    # proven": a caller that cannot say gets no credit for it.
    distinct_organizations: int = 0
    verification_level: VerificationLevel = VerificationLevel.UNVERIFIED


def wilson_lower_bound(successes: int, failures: int, z: float = 1.96) -> float:
    """Confidence that this will work, penalised for thin evidence.

    A plain success rate says 100% after a single lucky run. The Wilson lower
    bound says ~21%, which is the honest answer and the one an agent should
    act on. Same few lines, correct at small n.
    """
    total = successes + failures
    if total == 0:
        return 0.0
    phat = successes / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def corroborated_successes(successful_runs: int, distinct_organizations: int) -> int:
    """Successes that more than one actor's say-so could have produced.

    Wilson answers "how sure are we, given this many observations" and assumes
    the observations are independent. A thousand runs by the organization that
    wrote the artifact are one observation repeated a thousand times, so they
    are capped instead of accumulating: the honest count is bounded by how
    many organizations actually ran it.
    """
    return min(successful_runs, max(distinct_organizations, 1) * RUNS_PER_ORGANIZATION_CAP)


def corroboration_score(distinct_organizations: int) -> float:
    """Breadth of agreement, in [0, 1]. Distinct from usage: a hundred runs by
    one org and a hundred runs across ten orgs are not the same evidence."""
    return min(1.0, distinct_organizations / CORROBORATION_SATURATION)


def confidence_score(
    successful_runs: int,
    failed_runs: int,
    distinct_organizations: int,
    verification_level: VerificationLevel,
) -> float:
    """The number an agent should act on, and the one stored as evidence.

    Wilson itself is untouched -- 1/0 is still 20.7%, 100/0 still 96.3%. What
    changed is what gets fed to it and what comes out of it: the successes are
    capped per organization, and the result is scaled by how strong the proof
    was. Both are discounts on the same claim, so both multiply.
    """
    proven = wilson_lower_bound(
        corroborated_successes(successful_runs, distinct_organizations), failed_runs
    )
    return proven * VERIFICATION_STRENGTH[verification_level]


def minimum_corroborating_organizations() -> int:
    """The promotion threshold, read here so "use" and VERIFIED cannot disagree.

    This is a trust policy rather than a ranking weight, which is why it is the
    one number in this module that comes from configuration.
    """
    return settings().evidence.min_promotion_organizations


def usage_score(successful_runs: int) -> float:
    """Diminishing returns: 1 run matters a lot, run 1001 barely at all."""
    return min(1.0, math.log10(successful_runs + 1) / 3.0)


def recency_score(last_verified_at: datetime | None) -> float:
    if last_verified_at is None:
        return 0.0
    age_hours = (now() - last_verified_at).total_seconds() / 3600.0
    if age_hours <= FRESH_HOURS:
        return 1.0
    decay = (age_hours - FRESH_HOURS) / (STALE_AFTER_DAYS * 24.0)
    return max(0.0, 1.0 - decay)


def latency_score(median_duration_ms: int | None) -> float:
    """Faster is better, flattening out: 100ms and 400ms are both just fast."""
    if median_duration_ms is None:
        return 0.5
    return 1.0 / (1.0 + median_duration_ms / 5000.0)


def risk_score(signals: Signals) -> float:
    """Permission risk, as a penalty in [0, 1]. Network is the big one."""
    risk = 0.6 if signals.requires_network else 0.0
    risk += min(0.4, 0.1 * len(signals.required_capabilities))
    return min(1.0, risk)


COMPATIBILITY_SCORE = {
    Compatibility.HIGH: 1.0,
    Compatibility.PARTIAL: 0.5,
    Compatibility.NONE: 0.0,
}


def order(scores: dict[str, float]) -> list[str]:
    """Ids best-first, for rank-based fusion."""
    return sorted(scores, key=lambda key: scores[key], reverse=True)


def relevance_of(
    lexical_rank: float | None, cosine_similarity: float | None, top_lexical_rank: float = 0.0
) -> float:
    """How well this candidate actually matches the task, in [0, 1].

    Two retrievers disagree about scale, so take the stronger claim rather than
    averaging: a strong lexical hit and a strong semantic hit are each
    sufficient evidence that this is the same task.

    The lexical rank is scaled by the best rank in this query's candidate set
    once that exceeds LEXICAL_SCALE. A fixed divisor clamped every decent hit
    to 1.0, so for a goal statement quoted verbatim a dozen neighbours tied
    with the exact match and it came back twelfth. Only the best lexical hit
    may score 1.0 on this axis; a query too weak to reach the scale keeps the
    fixed divisor, so one poor hit does not get promoted to perfect.
    """
    divisor = max(LEXICAL_SCALE, top_lexical_rank)
    lexical = min(1.0, (lexical_rank or 0.0) / divisor)
    return max(lexical, cosine_similarity or 0.0)


def _names_a_conversion(intent: str) -> bool:
    """Whether a label names both a source and a target, e.g. `csv_to_jsonl`."""
    return "_to_" in intent


def intent_relevance(relevance: float, query_intent: str, candidate_intent: str) -> float:
    """Adjust how well this candidate MATCHES, given what each side calls the job.

    Never touches evidence: this says whether the task is the same one, not
    whether the Experience works.
    """
    if query_intent == candidate_intent:
        return min(1.0, relevance + INTENT_MATCH_BONUS)
    if _names_a_conversion(query_intent) and _names_a_conversion(candidate_intent):
        return relevance * INTENT_MISMATCH_FACTOR
    return relevance


def score(signals: Signals) -> tuple[float, float]:
    """Return (final_score, confidence).

    Relevance multiplies rather than adds. Evidence can only amplify a match
    that is already the right thing -- no amount of proven runs should let an
    Experience win a task it does not perform.
    """
    confidence = confidence_score(
        signals.successful_runs,
        signals.failed_runs,
        signals.distinct_organizations,
        signals.verification_level,
    )
    parts = {
        "compatibility": COMPATIBILITY_SCORE[signals.compatibility],
        "confidence": confidence,
        "usage": usage_score(signals.successful_runs),
        "corroboration": corroboration_score(signals.distinct_organizations),
        "recency": recency_score(signals.last_verified_at),
        "latency": latency_score(signals.median_duration_ms),
        "risk": 1.0 - risk_score(signals),
    }
    quality = sum(QUALITY_WEIGHTS[key] * value for key, value in parts.items())
    weight = signals.relevance**RELEVANCE_EXPONENT
    total = weight * (RELEVANCE_FLOOR + (1.0 - RELEVANCE_FLOOR) * quality)
    return total, confidence


def recommend(final_score: float, signals: Signals) -> Recommendation:
    """ "use" is the strongest thing this system says, so it has two conditions.

    Score alone is not enough. Weights are continuous, and a continuous weight
    cannot express "this has only ever been proven by the actor who published
    it" -- no plausible weight both leaves an uncorroborated Experience below
    0.70 and lets a corroborated one climb. So corroboration is a gate, exactly
    like incompatibility: below the threshold the best available answer is
    "consider", never "run it".
    """
    if signals.compatibility is Compatibility.NONE:
        return Recommendation.AVOID
    corroborated = signals.distinct_organizations >= minimum_corroborating_organizations()
    if final_score >= USE_THRESHOLD and corroborated:
        return Recommendation.USE
    if final_score >= CONSIDER_THRESHOLD:
        return Recommendation.CONSIDER
    return Recommendation.AVOID


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Merge lexical and vector candidate lists without tuning a mixing ratio.

    RRF only needs each list's ordering, so a BM25 score and a cosine distance
    can be combined without pretending they are on the same scale.
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + position + 1)
    return fused
