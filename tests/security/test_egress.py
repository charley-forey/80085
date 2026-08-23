"""Egress filtering (spec section 16).

`network: true` is set by the artifact's own author, with nobody approving it.
So these tests take the attacker's side: they record the flag, ask for the
network, and then go for the two things worth stealing -- the cloud metadata
service that hands out IAM credentials, and whatever is listening on the
worker's own private network.

Both must be refused. "Refused" has two shapes and both count: the packet is
dropped by the filter, or the run never starts because the filter could not be
installed. What must never happen is a container that reaches either one.

If one of these fails, fix the sandbox -- never relax the test.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from boobs_common.errors import ExecutionFailed
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import DockerOciRuntime
from boobs_execution.docker_oci import EGRESS_NETWORK

pytestmark = [pytest.mark.security, pytest.mark.usefixtures("docker")]

DIGESTS = Path(__file__).resolve().parents[2] / "capabilities" / "digests.json"
LISTENER_PORT = 8080


@pytest.fixture(scope="module")
def image() -> str:
    if not DIGESTS.is_file():
        pytest.skip("run scripts/build_capabilities.py first")
    return str(json.loads(DIGESTS.read_text())["csv_to_json"])


async def attempt(image: str, code: str) -> SandboxResult | str:
    """Run a networked artifact. Returns the result, or why it was refused."""
    request = SandboxRequest(
        execution_id=f"egr{abs(hash(code)) % 10**9}",
        image=image,
        command=["python", "-c", code],
        cpu=1.0,
        memory_mb=256,
        tmpfs_mb=64,
        timeout_seconds=30,
        pids=32,
        max_output_bytes=65536,
        network=True,
    )
    try:
        return await DockerOciRuntime().execute(request)
    except ExecutionFailed as refusal:
        return str(refusal)


def assert_unreachable(outcome: SandboxResult | str) -> None:
    if isinstance(outcome, str):
        assert "refusing to run a networked artifact" in outcome
        return
    assert outcome.exit_code != 0, outcome.stdout
    assert outcome.status is not ExecutionStatus.SUCCEEDED
    assert b"reachable" not in outcome.stdout


async def test_cloud_metadata_is_unreachable_with_network_true(image: str) -> None:
    """169.254.169.254 is one HTTP GET away from the worker's IAM credentials."""
    outcome = await attempt(
        image,
        "import socket\n"
        "s = socket.create_connection(('169.254.169.254', 80), timeout=5)\n"
        "s.sendall(b'GET /latest/meta-data/iam/security-credentials/ HTTP/1.0\\r\\n\\r\\n')\n"
        "print('reachable', s.recv(64))\n",
    )
    assert_unreachable(outcome)


async def test_link_local_is_unreachable_with_network_true(image: str) -> None:
    """The whole 169.254.0.0/16 range, not just the address everyone knows."""
    outcome = await attempt(
        image,
        "import socket\n"
        "socket.create_connection(('169.254.170.2', 80), timeout=5)\n"
        "print('reachable')\n",
    )
    assert_unreachable(outcome)


async def test_the_hosts_own_gateway_is_unreachable_with_network_true(image: str) -> None:
    """The default route points at the host. Everything on it must be refused."""
    outcome = await attempt(
        image,
        "import socket, struct\n"
        "gateway = ''\n"
        "for line in open('/proc/net/route').read().splitlines()[1:]:\n"
        "    fields = line.split()\n"
        "    if fields[1] == '00000000':\n"
        "        gateway = socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))\n"
        "for port in (22, 80, 443, 2375, 5000, 8000):\n"
        "    try:\n"
        "        socket.create_connection((gateway, port), timeout=3).close()\n"
        "    except OSError:\n"
        "        continue\n"
        "    print('reachable', gateway, port)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(7)\n",
    )
    assert_unreachable(outcome)


async def test_a_private_peer_is_unreachable_with_network_true(image: str) -> None:
    """The strong one: a real listener, on a real RFC1918 address, refused.

    Everything else here can pass on a laptop for the wrong reason -- nothing
    answers on 169.254.169.254 at home. This one puts a service that *does*
    answer on the same network as the sandbox and requires the filter to be
    what stops it.
    """
    runtime = DockerOciRuntime()
    try:
        network = await runtime._egress_network()  # noqa: SLF001 - setting up the attack
    except ExecutionFailed as refusal:
        pytest.skip(f"egress filter cannot be installed on this host: {refusal}")

    listener = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--detach",
            f"--network={network}",
            image,
            "python",
            "-c",
            "import socket\n"
            "s = socket.socket()\n"
            "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            f"s.bind(('0.0.0.0', {LISTENER_PORT}))\n"
            "s.listen(8)\n"
            "while True:\n"
            "    connection, _ = s.accept()\n"
            "    connection.sendall(b'reachable')\n"
            "    connection.close()\n",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    try:
        details = json.loads(
            subprocess.run(
                ["docker", "inspect", listener], capture_output=True, text=True, check=True
            ).stdout
        )
        address = details[0]["NetworkSettings"]["Networks"][EGRESS_NETWORK]["IPAddress"]
        assert address, "the listener has no address on the sandbox network"
        await asyncio.sleep(2)  # let it bind before the sandbox goes for it

        outcome = await attempt(
            image,
            "import socket\n"
            f"s = socket.create_connection(('{address}', {LISTENER_PORT}), timeout=5)\n"
            "print('reachable', s.recv(32))\n",
        )
        assert_unreachable(outcome)
    finally:
        subprocess.run(["docker", "rm", "-f", listener], capture_output=True, check=False)


async def test_a_networked_run_is_refused_when_the_filter_cannot_be_installed(
    image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed. A control that switches itself off when it cannot run is not one."""
    monkeypatch.setattr("boobs_execution.docker_oci.shutil.which", lambda _: None)
    outcome = await attempt(image, "print('reachable')")
    assert isinstance(outcome, str)
    assert "refusing to run a networked artifact" in outcome
    assert "iptables -I DOCKER-USER 1 -i" in outcome  # it says how to fix it
