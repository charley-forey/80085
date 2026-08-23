"""Sandbox runtimes, chosen by environment.

`BOOBS_RUNTIME=docker` (the default) keeps the local Docker daemon that every
existing install already uses. `BOOBS_RUNTIME=e2b` moves execution into
Firecracker microVMs, which is how the platform stops depending on one host
staying awake.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from boobs_domain.protocols import ExecutionRuntime
from boobs_execution.cache import CachingRuntime, cache_key
from boobs_execution.docker_oci import DockerOciRuntime
from boobs_execution.e2b_runtime import E2BRuntime

__all__ = ["CachingRuntime", "DockerOciRuntime", "E2BRuntime", "cache_key", "runtime"]

RUNTIMES: dict[str, Callable[[], ExecutionRuntime]] = {
    "docker": DockerOciRuntime,
    "e2b": E2BRuntime,
}


def runtime() -> ExecutionRuntime:
    """BOOBS_RUNTIME=docker|e2b, BOOBS_EXEC_CACHE=0|1.

    Defaults to Docker with the cache off, so an existing worker behaves
    exactly as it did before either of these existed. A replay is now safe to
    report -- the API records it and counts it as neither a success nor a
    failure -- but it is still not free: what it costs is the evidence that run
    would have produced (DECISIONS 51).
    """
    choice = os.environ.get("BOOBS_RUNTIME", "docker").strip().lower()
    if choice not in RUNTIMES:
        raise ValueError(
            f"BOOBS_RUNTIME={choice!r} is not a runtime; use one of {sorted(RUNTIMES)}"
        )
    selected: ExecutionRuntime = RUNTIMES[choice]()
    if os.environ.get("BOOBS_EXEC_CACHE", "0").strip() == "1":
        # Still loud, for the opposite reason to before: replays no longer
        # inflate evidence, they withhold it. A run served from this cache
        # produces no verification, no duration sample and no corroborating
        # organization, so an artifact nobody executes twice on this worker is
        # an artifact that stops accumulating proof.
        logging.getLogger(__name__).warning(
            "BOOBS_EXEC_CACHE=1: identical reruns are replayed from a local cache. "
            "Replays are reported with cached=true and count as neither a success "
            "nor a failure, so they generate no evidence at all -- including the "
            "second organization a candidate needs to be promoted."
        )
        selected = CachingRuntime(selected)
    return selected
