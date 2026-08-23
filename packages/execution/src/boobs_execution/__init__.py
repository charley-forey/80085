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
    exactly as it did before either of these existed. Read
    `boobs_execution.cache` before turning the cache on: a replayed result must
    not be recorded as a fresh verification run.
    """
    choice = os.environ.get("BOOBS_RUNTIME", "docker").strip().lower()
    if choice not in RUNTIMES:
        raise ValueError(
            f"BOOBS_RUNTIME={choice!r} is not a runtime; use one of {sorted(RUNTIMES)}"
        )
    selected: ExecutionRuntime = RUNTIMES[choice]()
    if os.environ.get("BOOBS_EXEC_CACHE", "0").strip() == "1":
        # Loud, like the embedder fallback: a caller that reports results as
        # evidence and does not honour `SandboxResult.cached` will record runs
        # that never happened, and silent evidence inflation is the failure
        # mode that would be hardest to notice from outside.
        logging.getLogger(__name__).warning(
            "BOOBS_EXEC_CACHE=1: identical reruns are replayed from a local cache. "
            "Results carry SandboxResult.cached=True; anything that turns results "
            "into evidence must exclude them or evidence counts will be inflated."
        )
        selected = CachingRuntime(selected)
    return selected
