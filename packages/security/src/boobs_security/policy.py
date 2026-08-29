"""Authorization: scopes plus tenancy (spec sections 16 and 30).

Every read of a tenant-owned object goes through `visible_to` and every action
through `authorize`. Keeping both here means tenant isolation is one file to
audit, not a rule scattered across every endpoint.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Protocol

from boobs_common.config import ExecutionTier
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
    # Issuing a key to a colleague inside your own organization. Named
    # separately from admin.keys because it is the one admin action an
    # ordinary enterprise deployment performs weekly rather than once.
    "admin.provision": Scope.ADMIN,
    # Reading what everyone asked for and did not find. Its own name rather
    # than a reuse of admin.keys because this list is the audit surface for
    # "which actions exist"; an action called `keys` guarding a demand report
    # would make that list a lie. Not a MUTATING_ACTION: it is a read, and it
    # is called with no resource because the rows span every tenant.
    "admin.misses": Scope.ADMIN,
    # Approving one organization for the longer execution tiers. Its own name,
    # for the same reason `admin.misses` has one: this list is the audit
    # surface for which actions exist, and `extended` is an hour of compute per
    # execution -- the most expensive thing any action here can hand out.
    "admin.execution_tiers": Scope.ADMIN,
    # Withdrawing one Experience from recall, or putting it back. Its own name
    # for the same reason the two above have one -- this list is the audit
    # surface for which actions exist -- and because it is the only action that
    # reaches across tenants to change what the corpus recommends. Everything
    # else an admin can do here hands something out; this one takes it away.
    "admin.quarantine": Scope.ADMIN,
}

# Actions that change an object. These require ownership, never visibility.
MUTATING_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "experience.record",
        "admin.keys",
        "admin.provision",
        "admin.execution_tiers",
        "admin.quarantine",
    }
)

# The policy row the grant endpoint owns. An operator's hand-written `INSERT`
# under any other name still grants -- `granted_tiers` unions every row -- which
# is why the endpoint answers with the effective set and not merely its own.
TIER_GRANT_POLICY: Final = "execution-tiers"

# Verifiers that check what the run produced, not merely that it exited zero.
# `exit_code` is the floor: an artifact that mines for an hour and exits 0
# passes it, which is exactly the thing an hour-long tier must not buy.
STRONG_VERIFIERS: Final[frozenset[str]] = frozenset({"json_schema", "sha256"})


def granted_tiers(rules: Iterable[dict[str, object] | None]) -> frozenset[str]:
    """The tiers an organization has been approved for, from its policy rows.

    No endpoint writes these. That is the point: a longer run is granted by an
    operator, never claimed by the caller, because the alternative is handing
    every anonymous stranger an hour of networked compute per request.
    """
    granted: set[str] = set()
    for row in rules:
        values = (row or {}).get("execution_tiers")
        if isinstance(values, list):
            granted.update(str(value) for value in values)
    return frozenset(granted)


def resolve_execution_tier(
    requested: str, granted: frozenset[str], verifier: str | None
) -> tuple[ExecutionTier, str]:
    """Which tier this run actually gets, and why.

    Downgrades rather than refuses: an unapproved request still runs, it just
    runs with the limits everyone else gets. Returns the reason so the lease
    can say out loud that it cut someone back.
    """
    try:
        wanted = ExecutionTier(requested)
    except ValueError:
        return ExecutionTier.QUICK, f"unknown tier {requested!r}"
    if wanted is ExecutionTier.QUICK:
        return wanted, "default tier"
    if wanted not in granted:
        return ExecutionTier.QUICK, f"organization is not approved for {wanted}"
    if wanted is ExecutionTier.EXTENDED and (verifier or "") not in STRONG_VERIFIERS:
        return ExecutionTier.QUICK, (
            f"{wanted} needs a verifier that checks output, not {verifier or 'nothing'!r}"
        )
    return wanted, "approved"


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
