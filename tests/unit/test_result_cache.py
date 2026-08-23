"""The result cache must be exact about what "the same run" means.

Two failure modes matter and they point in opposite directions. A key that is
too loose serves one artifact's output for another's, which is silent
corruption. A key that is too tight never hits, which is merely useless. The
tests below pin the loose direction: every field that can change the output
must change the key.

The third property is the one the product depends on -- a replayed result is
marked `cached`, so nothing downstream can mistake it for an independent run.
"""

from __future__ import annotations

from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import CachingRuntime, cache_key

DIGEST = "sha256:" + "ab" * 32
PINNED = f"registry.example/80085/csv_to_json@{DIGEST}"


def request(**overrides: object) -> SandboxRequest:
    base: dict[str, object] = {
        "execution_id": "exec_1",
        "image": PINNED,
        "command": ["python", "convert.py"],
        "input_files": {"data.csv": b"a,b\n1,2\n"},
        "env": {"MODE": "strict"},
        "cpu": 1.0,
        "memory_mb": 256,
        "tmpfs_mb": 64,
        "timeout_seconds": 30,
        "pids": 32,
        "max_output_bytes": 65536,
        "network": False,
    }
    base.update(overrides)
    return SandboxRequest(**base)  # type: ignore[arg-type]


class Counting:
    """A runtime that records what it was asked to run."""

    def __init__(self, status: ExecutionStatus = ExecutionStatus.SUCCEEDED) -> None:
        self.calls = 0
        self._status = status

    async def execute(self, sandbox_request: SandboxRequest) -> SandboxResult:
        self.calls += 1
        return SandboxResult(
            status=self._status,
            exit_code=0 if self._status is ExecutionStatus.SUCCEEDED else 1,
            duration_ms=7,
            stdout=f"run {self.calls}".encode(),
        )


# ------------------------------------------------------------------------ key


def test_key_ignores_which_execution_asked() -> None:
    """Two executions of the same pinned artifact are the same computation."""
    assert cache_key(request(execution_id="exec_1")) == cache_key(request(execution_id="exec_2"))


def test_key_ignores_dictionary_ordering() -> None:
    inputs = {"b.csv": b"second", "a.csv": b"first"}
    reversed_inputs = dict(reversed(list(inputs.items())))
    assert cache_key(request(input_files=inputs)) == cache_key(request(input_files=reversed_inputs))


def test_key_changes_with_everything_that_changes_the_output() -> None:
    baseline = cache_key(request())
    variations = {
        "image": {"image": f"registry.example/80085/other@{DIGEST}"},
        "digest": {"image": f"registry.example/80085/csv_to_json@sha256:{'cd' * 32}"},
        "command": {"command": ["python", "other.py"]},
        "input content": {"input_files": {"data.csv": b"a,b\n9,9\n"}},
        "input name": {"input_files": {"renamed.csv": b"a,b\n1,2\n"}},
        "extra input": {"input_files": {"data.csv": b"a,b\n1,2\n", "extra.csv": b""}},
        "env": {"env": {"MODE": "lenient"}},
        "network": {"network": True},
        "memory": {"memory_mb": 512},
        "timeout": {"timeout_seconds": 60},
        "output cap": {"max_output_bytes": 1024},
    }
    for label, override in variations.items():
        assert cache_key(request(**override)) != baseline, f"{label} did not change the key"


def test_argument_boundaries_are_not_smearable() -> None:
    """`["a", "b"]` and `["ab"]` must not hash to the same command."""
    assert cache_key(request(command=["a", "b"])) != cache_key(request(command=["ab"]))


# -------------------------------------------------------------- hit and miss


async def test_identical_request_is_served_without_a_sandbox() -> None:
    inner = Counting()
    caching = CachingRuntime(inner)

    first = await caching.execute(request())
    second = await caching.execute(request(execution_id="exec_2"))

    assert inner.calls == 1
    assert second.stdout == first.stdout


async def test_a_replayed_result_says_so() -> None:
    """The whole safety story rests on this flag being set on hits only."""
    caching = CachingRuntime(Counting())

    first = await caching.execute(request())
    second = await caching.execute(request())

    assert first.cached is False
    assert second.cached is True


async def test_a_different_request_misses() -> None:
    inner = Counting()
    caching = CachingRuntime(inner)

    await caching.execute(request())
    await caching.execute(request(input_files={"data.csv": b"different"}))

    assert inner.calls == 2


async def test_failures_are_never_replayed() -> None:
    """A timeout is a property of the machine that day, not of the artifact."""
    inner = Counting(status=ExecutionStatus.TIMEOUT)
    caching = CachingRuntime(inner)

    await caching.execute(request())
    await caching.execute(request())

    assert inner.calls == 2


async def test_the_cache_has_a_ceiling() -> None:
    inner = Counting()
    caching = CachingRuntime(inner, capacity=2)

    for index in range(3):
        await caching.execute(request(input_files={"data.csv": str(index).encode()}))
    evicted = await caching.execute(request(input_files={"data.csv": b"0"}))

    assert inner.calls == 4
    assert evicted.cached is False
