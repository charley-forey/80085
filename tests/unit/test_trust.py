"""Evidence must cost more to fake than it is worth.

The audit found the whole chain under one actor's control: whoever records an
Experience declares its verifier, `exit_code` believes any container that exits
0, and the first passing run promoted the Experience to VERIFIED. Minting
organizations is free, so "verified" meant "someone bothered".

These tests pin the three places that chain is now broken.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from boobs_common.config import EvidencePolicy, Settings
from boobs_domain.enums import ExperienceStatus, VerificationLevel
from boobs_reputation.evidence import _withdraw, collapse, corroborated
from boobs_schemas.api import VerifyRequest


def test_one_organization_cannot_promote_its_own_experience() -> None:
    assert not corroborated(0)
    assert not corroborated(1)


def test_two_distinct_organizations_can() -> None:
    assert corroborated(2)
    assert corroborated(50)


def test_the_promotion_threshold_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single-tenant deployment has different maths, and should not have to
    patch the ranking code to say so."""
    monkeypatch.setenv("EVIDENCE_MIN_PROMOTION_ORGANIZATIONS", "4")
    assert EvidencePolicy().min_promotion_organizations == 4
    assert Settings().evidence.min_promotion_organizations == 4


def test_the_default_threshold_is_two() -> None:
    assert EvidencePolicy().min_promotion_organizations == 2


def test_verify_refuses_a_substituted_verifier() -> None:
    """The owner of an execution could re-verify their own run under a weaker
    verifier. There is now no field to do it with, and the request model
    forbids extras, so the attempt is rejected at the boundary."""
    VerifyRequest()
    with pytest.raises(ValidationError):
        VerifyRequest(verifier="exit_code")
    with pytest.raises(ValidationError):
        VerifyRequest(config={"expected": 0})


def test_an_operators_own_organizations_count_as_one_party() -> None:
    """The gate counts organizations because organizations are free. So is
    minting a second one for yourself, which is how a registry corroborates its
    own corpus without ever meaning to cheat."""
    ours = {"org_seed", "org_consumer"}

    # Two hats, one opinion: not enough to promote anything.
    assert collapse(ours, ours) == 1
    assert not corroborated(collapse(ours, ours))

    # One genuine outsider is what the gate was always asking for.
    assert collapse(ours | {"org_stranger"}, ours) == 2
    assert corroborated(collapse(ours | {"org_stranger"}, ours))


def test_organizations_nobody_claimed_still_count_individually() -> None:
    """This buys independence from the operator, not identity. Two strangers
    are two, and an empty first-party list changes nothing."""
    assert collapse({"a", "b"}, set()) == 2
    assert collapse({"a", "b"}, {"c"}) == 2
    assert collapse(set(), {"a"}) == 0


def test_first_party_organizations_are_named_in_one_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVIDENCE_FIRST_PARTY_ORGANIZATIONS", "acme-research, globex-labs ,smoke-*")
    assert EvidencePolicy().first_party() == frozenset({"acme-research", "globex-labs", "smoke-*"})
    # Unset means the gate behaves exactly as it did before.
    monkeypatch.delenv("EVIDENCE_FIRST_PARTY_ORGANIZATIONS")
    assert EvidencePolicy().first_party() == frozenset()


def test_verified_is_withdrawn_when_its_corroboration_collapses() -> None:
    """`_promote` was one-way, which was safe only while the count could not
    fall. Decision 70 made it fall: naming an organization as first-party
    collapses it into the operator, and an Experience promoted on two
    organizations that turn out to be one party is left asserting something
    nobody proved."""
    experience = SimpleNamespace(
        status=ExperienceStatus.VERIFIED,
        verification_level=VerificationLevel.PROVEN,
        updated_at=None,
    )
    _withdraw(experience)
    assert experience.status == ExperienceStatus.CANDIDATE
    assert experience.verification_level == VerificationLevel.UNVERIFIED


@pytest.mark.parametrize("status", [ExperienceStatus.QUARANTINED, ExperienceStatus.CANDIDATE])
def test_withdrawal_touches_nothing_but_verified(status: str) -> None:
    """Quarantine is somebody's judgement and is not ours to undo; a candidate
    has nothing to take back."""
    experience = SimpleNamespace(
        status=status, verification_level=VerificationLevel.UNVERIFIED, updated_at=None
    )
    _withdraw(experience)
    assert experience.status == status
