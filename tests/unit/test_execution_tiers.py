"""Execution tiers, and the flags that carry them.

A longer run is a bigger weapon: an hour of networked compute per anonymous
request is a mining pool with a REST API. So the length of a run is a tier an
operator grants, and everything that does not have a grant gets today's
limits.
"""

from __future__ import annotations

import pytest

from boobs_common.config import (
    TIER_TIMEOUT_SECONDS,
    ExecutionTier,
    SandboxLimits,
    tier_for_duration,
)
from boobs_execution.docker_oci import BLOCKED_DESTINATIONS, FILTERED_CHAINS, egress_rules
from boobs_security.policy import granted_tiers, resolve_execution_tier

EVERYTHING = frozenset({"standard", "extended"})


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (None, ExecutionTier.QUICK),
        (5, ExecutionTier.QUICK),
        (60, ExecutionTier.QUICK),
        (61, ExecutionTier.STANDARD),
        (600, ExecutionTier.STANDARD),
        (601, ExecutionTier.EXTENDED),
        (3600, ExecutionTier.EXTENDED),
    ],
)
def test_a_declared_duration_lands_in_the_smallest_tier_that_covers_it(
    declared: int | None, expected: ExecutionTier
) -> None:
    assert tier_for_duration(declared) is expected


def test_nothing_that_already_exists_changes() -> None:
    """No declared duration, no policy row: exactly the limits of before."""
    assert tier_for_duration(None) is ExecutionTier.QUICK
    assert SandboxLimits().for_tier(None).timeout_seconds == 60
    assert resolve_execution_tier("quick", frozenset(), None)[0] is ExecutionTier.QUICK


def test_a_higher_tier_is_never_self_serve() -> None:
    """Recording `max_duration_seconds: 3600` grants nothing by itself."""
    tier, reason = resolve_execution_tier("extended", frozenset(), "sha256")
    assert tier is ExecutionTier.QUICK
    assert "not approved" in reason


def test_the_hour_long_tier_also_needs_a_verifier_that_checks_output() -> None:
    """`exit_code` passes for an artifact that mines for an hour and exits 0."""
    downgraded, reason = resolve_execution_tier("extended", EVERYTHING, "exit_code")
    assert downgraded is ExecutionTier.QUICK
    assert "verifier" in reason
    assert resolve_execution_tier("extended", EVERYTHING, "sha256")[0] is ExecutionTier.EXTENDED
    assert resolve_execution_tier("standard", EVERYTHING, "exit_code")[0] is ExecutionTier.STANDARD


def test_an_unknown_tier_is_the_lowest_one() -> None:
    assert resolve_execution_tier("forever", EVERYTHING, "sha256")[0] is ExecutionTier.QUICK
    assert SandboxLimits().for_tier("forever").timeout_seconds == 60


def test_a_granted_tier_moves_the_wall_clock_and_nothing_else() -> None:
    """cpu/memory/tmpfs/pids are cgroup flags E2B does not enforce (DECISIONS 19),
    so tiering them would be a promise one runtime silently breaks."""
    base = SandboxLimits()
    extended = base.for_tier("extended")
    assert extended.timeout_seconds == TIER_TIMEOUT_SECONDS[ExecutionTier.EXTENDED]
    assert extended.model_dump(exclude={"timeout_seconds"}) == base.model_dump(
        exclude={"timeout_seconds"}
    )


def test_an_operators_longer_default_is_not_cut_back_by_the_default_tier() -> None:
    assert SandboxLimits(timeout_seconds=120).for_tier("quick").timeout_seconds == 120


def test_grants_come_from_policy_rows_and_union_across_them() -> None:
    assert granted_tiers([]) == frozenset()
    assert granted_tiers([None, {}, {"execution_tiers": "extended"}]) == frozenset()
    assert granted_tiers(
        [{"execution_tiers": ["standard"]}, {"execution_tiers": ["extended"]}]
    ) == frozenset({"standard", "extended"})


def test_every_private_range_is_dropped_on_both_chains() -> None:
    """Forwarded traffic and traffic addressed to the host are different paths.

    DOCKER-USER only sees the first, so a rule set that covered it alone would
    leave every service on the worker itself reachable from the sandbox.
    """
    rules = egress_rules()
    assert len(rules) == len(FILTERED_CHAINS) * len(BLOCKED_DESTINATIONS)
    for chain in FILTERED_CHAINS:
        dropped = {rule[rule.index("-d") + 1] for rule in rules if rule[0] == chain}
        assert {"169.254.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"} <= dropped
        assert all(rule[-1] == "DROP" for rule in rules if rule[0] == chain)


def test_a_networked_sandbox_never_joins_the_default_bridge() -> None:
    """`--network=bridge` is the whole vulnerability: it is unfiltered."""
    from boobs_domain.protocols import SandboxRequest
    from boobs_execution.docker_oci import EGRESS_NETWORK, DockerOciRuntime

    request = SandboxRequest(
        execution_id="tier1",
        image="ghcr.io/x/y@sha256:" + "0" * 64,
        command=["true"],
        cpu=1.0,
        memory_mb=64,
        tmpfs_mb=16,
        timeout_seconds=5,
        pids=8,
        max_output_bytes=1024,
        network=True,
    )
    args = DockerOciRuntime()._create_args(request, EGRESS_NETWORK)  # noqa: SLF001
    assert f"--network={EGRESS_NETWORK}" in args
    assert "--network=bridge" not in args
