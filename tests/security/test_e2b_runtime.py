"""E2B sandbox isolation -- the same attacks, a different boundary.

`test_sandbox.py` asserts properties that come from Docker flags: uid 65534,
a read-only rootfs, dropped capabilities. Those flags do not exist here and
should not be faked, because on E2B they are not what contains the artifact --
the Firecracker microVM is. What carries over are the properties the contract
actually promises a caller: no network unless asked, a wall clock that ends
the run, and output that cannot grow without bound.

Skipped loudly rather than mocked, like every other service-backed test here.
A mocked microVM would prove nothing about isolation.

These are slow: the first run against a given image builds an E2B template
from it, which is minutes, and E2B's builders must be able to pull that image
-- a `localhost:5000` reference from local development cannot work. Set
`BOOBS_E2B_TEST_IMAGE` to a digest-pinned reference on a registry E2B can
reach.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from boobs_common.errors import ExecutionFailed
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import E2BRuntime

pytestmark = pytest.mark.security

DIGESTS = Path(__file__).resolve().parents[2] / "capabilities" / "digests.json"


@pytest.fixture(scope="module", autouse=True)
def credentials() -> None:
    if not os.environ.get("E2B_API_KEY"):
        pytest.skip("E2B_API_KEY is not set; export an E2B key to run the E2B sandbox suite")


@pytest.fixture(scope="module")
def image() -> str:
    override = os.environ.get("BOOBS_E2B_TEST_IMAGE")
    if override:
        return override
    if not DIGESTS.is_file():
        pytest.skip("run scripts/build_capabilities.py first, or set BOOBS_E2B_TEST_IMAGE")
    reference = str(json.loads(DIGESTS.read_text())["csv_to_json"])
    if reference.startswith(("localhost", "127.0.0.1")):
        pytest.skip(
            f"{reference} lives on a local registry E2B cannot pull from; "
            "set BOOBS_E2B_TEST_IMAGE to a digest-pinned public reference"
        )
    return reference


async def run(image: str, code: str, **overrides: object) -> SandboxResult:
    request: dict[str, object] = {
        "execution_id": f"e2b{abs(hash(code)) % 10**9}",
        "image": image,
        "command": ["python", "-c", code],
        "cpu": 1.0,
        "memory_mb": 256,
        "tmpfs_mb": 64,
        "timeout_seconds": 30,
        "pids": 32,
        "max_output_bytes": 65536,
        # True, because the runtime refuses the other mode outright: E2B was
        # measured leaving outbound TCP open with internet access disabled, so
        # a no-network run is rejected rather than served unsafely. Everything
        # below therefore tests the isolation that survives WITH network.
        "network": True,
    }
    request.update(overrides)
    return await E2BRuntime().execute(SandboxRequest(**request))  # type: ignore[arg-type]


async def test_the_sandbox_runs_the_command_at_all(image: str) -> None:
    """The floor: if this fails, nothing below it means anything."""
    result = await run(image, "print('alive')")
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.stdout.strip() == b"alive"


async def test_a_no_network_artifact_is_refused_rather_than_run(image: str) -> None:
    """The isolated-network promise is not one this runtime can keep.

    Measured against the live service, twice, with our code out of the way:
    `allow_internet_access=False` and `network={"deny_out": ["0.0.0.0/0"]}`
    both left a sandbox able to open a TCP connection to 1.1.1.1:53. Only DNS
    is refused, which is what makes it look isolated -- a resolver failure
    reads as "no network" right up until something dials an address directly.

    `--network=none` is the first control in docs/security.md and the one that
    stops exfiltration, C2 and mining. Refusing is the honest failure: a
    hostile artifact told it has no network must not be handed the internet.
    """
    with pytest.raises(ExecutionFailed, match="cannot enforce an isolated network"):
        await run(image, "print('should never run')", network=False)


async def test_a_network_artifact_really_does_get_the_network(image: str) -> None:
    """The mode this runtime does serve, asserted so it is not accidental.

    Worth pinning because of how the missing isolation hid: under
    `allow_internet_access=False` DNS failed while raw TCP succeeded, so a
    resolver error read as "no network". Naming both halves keeps the next
    person from drawing that conclusion again.
    """
    result = await run(image, "import socket; socket.gethostbyname('example.com')")
    assert result.exit_code == 0


async def test_wall_clock_timeout_ends_the_run(image: str) -> None:
    result = await run(image, "import time; time.sleep(600)", timeout_seconds=5)
    assert result.status is ExecutionStatus.TIMEOUT


async def test_output_flood_is_truncated(image: str) -> None:
    result = await run(
        image,
        "import sys; sys.stdout.write('x' * 5_000_000)",
        max_output_bytes=4096,
    )
    assert result.truncated
    assert len(result.stdout) <= 4096


async def test_outputs_cannot_exceed_the_size_cap(image: str) -> None:
    result = await run(
        image,
        "open('big.bin', 'wb').write(b'x' * 3_000_000)",
        max_output_bytes=8192,
    )
    assert sum(len(blob) for blob in result.output_files.values()) <= 8192


async def test_inputs_are_staged_in_and_outputs_come_back(image: str) -> None:
    """Inputs must not reappear as outputs, or every run would echo itself."""
    result = await run(
        image,
        "open('out.txt', 'w').write(open('in.txt').read().upper())",
        input_files={"in.txt": b"hello"},
    )
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.output_files == {"out.txt": b"HELLO"}


async def test_an_input_name_cannot_escape_the_work_directory(image: str) -> None:
    with pytest.raises(ExecutionFailed, match="escapes"):
        await run(image, "pass", input_files={"../../etc/passwd": b"x"})
