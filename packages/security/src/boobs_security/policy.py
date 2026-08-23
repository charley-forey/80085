"""Authorization: scopes plus tenancy (spec sections 16 and 30).

Every read of a tenant-owned object goes through `visible_to` and every action
through `authorize`. Keeping both here means tenant isolation is one file to
audit, not a rule scattered across every endpoint.
"""

from __future__ import annotations

from typing import Final, Protocol

from boobs_common.errors import Forbidden
from boobs_domain.enums import Visibility
from boobs_domain.protocols import Principal
from boobs_security.keys import Scope


class Owned(Protocol):
    """Anything with an owner. Both ORM rows and domain entities satisfy it."""

    organization_id: str


ACTION_SCOPES: Final[dict[str, str]] = {
    "experience.read": Scope.EXPERIENCES_READ,
    "experience.recall": Scope.EXPERIENCES_READ,
    "experience.record": Scope.EXPERIENCES_WRITE,
    "execution.run": Scope.EXECUTIONS_RUN,
    "execution.read": Scope.EXPERIENCES_READ,
    "execution.verify": Scope.EXECUTIONS_VERIFY,
    "admin.keys": Scope.ADMIN,
}

# Actions that change an object. These require ownership, never visibility.
MUTATING_ACTIONS: Final[frozenset[str]] = frozenset({"experience.record", "admin.keys"})


def visible_to(
    principal: Principal, organization_id: str, visibility: str, created_by: str
) -> bool:
    """The single definition of who may see a tenant-owned object.

    private      -- the agent that created it
    organization -- any agent in the owning organization
    public       -- everyone, which is what makes cross-agent reuse possible
    """
    if visibility == Visibility.PUBLIC:
        return True
    if principal.organization_id != organization_id:
        return False
    if visibility == Visibility.PRIVATE:
        return principal.agent_id == created_by
    return True


class ScopePolicyEngine:
    """The MVP PolicyEngine: scope check, then ownership check.

    Richer rules (per-experience allowlists, network egress policy, cost caps)
    become additional checks here without touching call sites.
    """

    async def authorize(
        self, principal: Principal, action: str, resource: object | None = None
    ) -> None:
        required = ACTION_SCOPES.get(action)
        if required is None:
            raise Forbidden(f"unknown action {action!r}")
        if Scope.ADMIN not in principal.scopes and required not in principal.scopes:
            raise Forbidden(f"missing scope {required!r} for {action!r}")

        if resource is None:
            return

        owner = getattr(resource, "organization_id", None)
        if owner is None:
            return

        # Mutating an object requires owning it. Using one -- reading, recalling,
        # executing, verifying -- is governed by visibility, which is precisely
        # what lets agent B run agent A's public experience.
        if action in MUTATING_ACTIONS:
            if owner != principal.organization_id:
                raise Forbidden("cross-tenant write refused")
            return

        visibility = str(getattr(resource, "visibility", Visibility.PRIVATE))
        created_by = str(getattr(resource, "created_by", "") or "")
        if not visible_to(principal, owner, visibility, created_by):
            raise Forbidden("not visible to this principal")
