"""Evidence must cost more to fake than it is worth.

The audit found the whole chain under one actor's control: whoever records an
Experience declares its verifier, `exit_code` believes any container that exits
0, and the first passing run promoted the Experience to VERIFIED. Minting
organizations is free, so "verified" meant "someone bothered".

These tests pin the three places that chain is now broken.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from boobs_common.config import EvidencePolicy, Settings
from boobs_reputation.evidence import corroborated
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
