"""Sandbox isolation (spec section 16).

Every artifact is hostile until proven otherwise, so these tests attack the
sandbox with the real thing: real containers, real payloads, real limits. If
one of these ever fails, the correct response is to fix the sandbox -- never
to relax the test.

The payloads run inside an already-built capability image, which ships a
Python interpreter. That is not cheating: an attacker with an artifact in the
registry has exactly this much freedom.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import DockerOciRuntime

pytestmark = [pytest.mark.security, pytest.mark.usefixtures("docker")]

DIGESTS = Path(__file__).resolve().parents[2] / "capabilities" / "digests.json"


@pytest.fixture(scope="module")
def image() -> str:
    if not DIGESTS.is_file():
        pytest.skip("run scripts/build_capabilities.py first")
    return str(json.loads(DIGESTS.read_text())["csv_to_json"])


async def run(image: str, code: str, **overrides: object) -> SandboxResult:
    request: dict[str, object] = {
        "execution_id": f"sec{abs(hash(code)) % 10**9}",
        "image": image,
        "command": ["python", "-c", code],
        "cpu": 1.0,
        "memory_mb": 256,
        "tmpfs_mb": 64,
        "timeout_seconds": 30,
        "pids": 32,
        "max_output_bytes": 65536,
        "network": False,
    }
    request.update(overrides)
    return await DockerOciRuntime().execute(SandboxRequest(**request))  # type: ignore[arg-type]


async def test_network_is_unreachable(image: str) -> None:
    result = await run(
        image,
        "import socket; socket.create_connection(('1.1.1.1', 53), timeout=5)",
    )
    assert result.exit_code != 0
    assert result.status is not ExecutionStatus.SUCCEEDED


async def test_dns_resolution_fails_too(image: str) -> None:
    result = await run(image, "import socket; socket.gethostbyname('example.com')")
    assert result.exit_code != 0


async def test_root_filesystem_is_read_only(image: str) -> None:
    result = await run(image, "open('/etc/80085-owned', 'w').write('pwned')")
    assert result.exit_code != 0
    assert b"Read-only file system" in result.stderr


async def test_process_is_not_root(image: str) -> None:
    result = await run(image, "import os; print(os.getuid(), os.geteuid())")
    assert result.exit_code == 0
    assert result.stdout.strip() == b"65534 65534"


async def test_privilege_escalation_is_refused(image: str) -> None:
    result = await run(image, "import os; os.setuid(0)")
    assert result.exit_code != 0


async def test_docker_socket_is_absent(image: str) -> None:
    """A reachable daemon socket would turn any artifact into a host takeover."""
    result = await run(image, "import os; print(os.path.exists('/var/run/docker.sock'))")
    assert result.exit_code == 0
    assert result.stdout.strip() == b"False"


async def test_the_only_writable_real_filesystem_is_the_work_directory(image: str) -> None:
    """A host bind mount would appear here as a writable non-pseudo filesystem.

    Kernel pseudo-filesystems (proc, sysfs, tmpfs, cgroup...) are always
    writable and are not storage, so they are excluded by type rather than by
    name -- excluding by name is how a real mount slips through.
    """
    pseudo = {
        "proc",
        "sysfs",
        "tmpfs",
        "devtmpfs",
        "devpts",
        "mqueue",
        "cgroup",
        "cgroup2",
        "securityfs",
        "ramfs",
        "fusectl",
        "debugfs",
    }
    result = await run(image, "print(open('/proc/mounts').read())")
    assert result.exit_code == 0

    writable_storage = {
        fields[1]
        for line in result.stdout.decode().splitlines()
        if (fields := line.split())
        and len(fields) > 3
        and fields[2] not in pseudo
        and fields[3].split(",")[0] == "rw"
    }
    assert writable_storage == {"/work"}, f"unexpected writable storage: {writable_storage}"


async def test_wall_clock_timeout_kills_the_container(image: str) -> None:
    result = await run(image, "import time; time.sleep(600)", timeout_seconds=5)
    assert result.status is ExecutionStatus.TIMEOUT
    assert result.duration_ms < 30_000


async def test_fork_bomb_is_contained_by_the_pid_limit(image: str) -> None:
    """It may fail or be killed; what it must not do is run away."""
    result = await run(
        image,
        "import os\nwhile True:\n    os.fork()",
        pids=24,
        timeout_seconds=20,
    )
    assert result.status is not ExecutionStatus.SUCCEEDED


async def test_memory_hog_is_killed(image: str) -> None:
    result = await run(
        image,
        "buf = bytearray()\nwhile True:\n    buf.extend(b'x' * (10 * 1024 * 1024))",
        memory_mb=128,
        timeout_seconds=30,
    )
    assert result.status is not ExecutionStatus.SUCCEEDED


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
