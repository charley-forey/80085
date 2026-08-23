"""Tenant isolation and key handling. These are the tests that must not be
made to pass by weakening the thing they test."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from boobs_common.errors import Forbidden
from boobs_domain.enums import Visibility
from boobs_domain.protocols import Principal
from boobs_security.keys import Scope, generate, hash_key, looks_like_key, matches
from boobs_security.policy import ScopePolicyEngine, visible_to


@dataclass
class Resource:
    organization_id: str
    visibility: str
    created_by: str


ACME = Principal(organization_id="org_acme", agent_id="agt_a", scopes=Scope.ALL)
GLOBEX = Principal(organization_id="org_globex", agent_id="agt_b", scopes=Scope.ALL)
ACME_OTHER_AGENT = Principal(organization_id="org_acme", agent_id="agt_z", scopes=Scope.ALL)


def test_key_is_never_stored_in_plaintext() -> None:
    plaintext, key_hash = generate()
    assert looks_like_key(plaintext)
    assert plaintext not in key_hash
    assert key_hash == hash_key(plaintext)
    assert matches(plaintext, key_hash)
    assert not matches(plaintext + "x", key_hash)


def test_private_is_visible_only_to_its_author() -> None:
    assert visible_to(ACME, "org_acme", Visibility.PRIVATE, "agt_a")
    assert not visible_to(ACME_OTHER_AGENT, "org_acme", Visibility.PRIVATE, "agt_a")
    assert not visible_to(GLOBEX, "org_acme", Visibility.PRIVATE, "agt_a")


def test_organization_visibility_stops_at_the_tenant_boundary() -> None:
    assert visible_to(ACME_OTHER_AGENT, "org_acme", Visibility.ORGANIZATION, "agt_a")
    assert not visible_to(GLOBEX, "org_acme", Visibility.ORGANIZATION, "agt_a")


def test_public_crosses_tenants_because_that_is_the_product() -> None:
    assert visible_to(GLOBEX, "org_acme", Visibility.PUBLIC, "agt_a")


async def test_missing_scope_is_refused() -> None:
    limited = Principal(
        organization_id="org_acme", agent_id="agt_a", scopes=frozenset({Scope.EXPERIENCES_READ})
    )
    with pytest.raises(Forbidden):
        await ScopePolicyEngine().authorize(limited, "experience.record")


async def test_another_tenant_cannot_write_your_experience() -> None:
    resource = Resource("org_acme", Visibility.PUBLIC, "agt_a")
    with pytest.raises(Forbidden):
        await ScopePolicyEngine().authorize(GLOBEX, "experience.record", resource)


async def test_another_tenant_can_run_your_public_experience() -> None:
    """Cross-agent reuse is the product; this must stay allowed."""
    resource = Resource("org_acme", Visibility.PUBLIC, "agt_a")
    await ScopePolicyEngine().authorize(GLOBEX, "execution.run", resource)


async def test_another_tenant_cannot_run_your_private_experience() -> None:
    resource = Resource("org_acme", Visibility.PRIVATE, "agt_a")
    with pytest.raises(Forbidden):
        await ScopePolicyEngine().authorize(GLOBEX, "execution.run", resource)


async def test_unknown_action_is_refused_rather_than_allowed() -> None:
    with pytest.raises(Forbidden):
        await ScopePolicyEngine().authorize(ACME, "experience.delete_everything")
