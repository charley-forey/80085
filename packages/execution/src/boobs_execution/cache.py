"""Content-addressed result cache, in front of any runtime.

An artifact is pinned by digest (DECISIONS 13), so the same digest, command,
inputs, environment, network flag and resource limits produce the same bytes.
Running that again buys a sandbox and nothing else.

**Which is exactly why it must not buy evidence either.** The API counts one
terminal `executions` row as one independent verification run
(`boobs_reputation.evidence.recompute`), and it learns about that run from
whatever the worker reports. If a worker served a cached result and reported
it like any other, the platform would record a verification of a run that
never happened -- and evidence is the entire product. So:

* a cache hit is stamped `SandboxResult.cached`, the worker sends it on every
  result, and the API records it on `executions.cached`, does not verify it,
  and excludes it from both counts in `recompute` (DECISIONS 51);
* the worker still leaves the cache **off** by default, but no longer because
  a replay would inflate evidence. It is off because a replay produces *no*
  evidence: a second organization running this artifact would be served the
  first organization's bytes, `distinct_organizations` would never reach two,
  and the Experience would never be promoted. The cache trades evidence for
  compute, so turning it on is an operator's call.

Only successes are cached. A non-zero exit may be deterministic, but a timeout
or an out-of-memory kill depends on what else the machine was doing, and
replaying one as if it were a property of the artifact would be a lie in the
other direction.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import ExecutionRuntime, SandboxRequest, SandboxResult

DEFAULT_CAPACITY = 256
_FIELD = b"\x1e"
_PAIR = b"\x1f"


def cache_key(request: SandboxRequest) -> str:
    """Everything that can change the output, and nothing that cannot.

    `execution_id` is excluded on purpose: two executions of the same pinned
    artifact with the same inputs are the same computation, which is the whole
    point. Inputs are hashed by content and sorted by name so that dictionary
    ordering cannot produce two keys for one request.
    """
    digest = hashlib.sha256()

    def field(value: bytes) -> None:
        digest.update(value)
        digest.update(_FIELD)

    field(request.image.encode())
    field(_PAIR.join(part.encode() for part in request.command))
    field(b"net" if request.network else b"nonet")
    field(
        f"{request.cpu}|{request.memory_mb}|{request.tmpfs_mb}|"
        f"{request.timeout_seconds}|{request.pids}|{request.max_output_bytes}".encode()
    )
    for name in sorted(request.env):
        field(name.encode() + _PAIR + request.env[name].encode())
    field(b"end-env")
    for name in sorted(request.input_files):
        content = hashlib.sha256(request.input_files[name]).hexdigest()
        field(name.encode() + _PAIR + content.encode())
    return digest.hexdigest()


class CachingRuntime:
    """An `ExecutionRuntime` that answers repeats without starting a sandbox.

    Wraps any runtime, so Docker and E2B both get it and nothing above the
    protocol changes.
    """

    def __init__(self, inner: ExecutionRuntime, capacity: int = DEFAULT_CAPACITY) -> None:
        self._inner = inner
        self._capacity = capacity
        # ponytail: in-process LRU. It dies with the worker and is not shared
        # between workers, so the hit rate is only as good as one process's
        # history. Upgrade path when that matters: store key -> SandboxResult
        # in Postgres (outputs already go to object storage), read through the
        # API so every worker shares one cache.
        self._entries: OrderedDict[str, SandboxResult] = OrderedDict()

    async def execute(self, request: SandboxRequest) -> SandboxResult:
        key = cache_key(request)
        hit = self._entries.get(key)
        if hit is not None:
            self._entries.move_to_end(key)
            return hit.model_copy(update={"cached": True})

        result = await self._inner.execute(request)
        if result.status is ExecutionStatus.SUCCEEDED:
            self._entries[key] = result
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
        return result
