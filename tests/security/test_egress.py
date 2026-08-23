"""Egress filtering (spec section 16).

`network: true` is set by the artifact's own author, with nobody approving it.
So these tests take the attacker's side: they record the flag, ask for the
network, and then go for the two things worth stealing -- the cloud metadata
service that hands out IAM credentials, and whatever is listening on the
worker's own private network.

Both must be refused, and these tests insist on the *strong* shape: the packet
is dropped by an installed rule. The weak shape -- the run never starts because
the filter could not be installed -- is also safe, and it has its own test at
the bottom, but it is not evidence that filtering works.

Conflating the two is exactly how this suite lied for weeks. A refusal counted
as a pass, so on any host without CAP_NET_ADMIN three of these went green
without a rule ever existing, and the two that would have noticed skipped
instead. Every environment this had ever run in -- Windows, CI, production --
was such a host.

If one of these fails, fix the sandbox -- never relax the test.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from boobs_common.errors import RuntimeUnavailable
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import DockerOciRuntime
from boobs_execution.docker_oci import EGRESS_NETWORK, egress_rule

pytestmark = [pytest.mark.security, pytest.mark.usefixtures("docker")]

DIGESTS = Path(__file__).resolve().parents[2] / "capabilities" / "digests.json"
LISTENER_PORT = 8080
LISTENER = (
    "import socket\n"
    "s = socket.socket()\n"
    "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    f"s.bind(('0.0.0.0', {LISTENER_PORT}))\n"
    "s.listen(8)\n"
    "while True:\n"
    "    connection, _ = s.accept()\n"
    "    connection.sendall(b'reachable')\n"
    "    connection.close()\n"
)


@pytest.fixture(scope="module")
def image() -> str:
    if not DIGESTS.is_file():
        pytest.skip("run scripts/build_capabilities.py first")
    return str(json.loads(DIGESTS.read_text())["csv_to_json"])


@pytest.fixture(scope="module")
async def filtering() -> str:
    """The sandbox network, with the DROP rules actually installed.

    Every test that claims a packet was *dropped* depends on this. It is a
    fixture rather than a try/except at each call site because of how this
    suite was wrong before: a refusal was accepted as proof of filtering, so
    three tests went green on an unprivileged runner without a rule ever
    existing, and the two that would have noticed skipped. A skip is not a
    failure, so nothing was ever red.

    The distinction that matters is between a host that *cannot* filter and a
    host that *should* and does not:

    * not Linux -- there is no iptables to install into, so the claim is
      untestable here and skipping is honest.
    * Linux, and the filter will not install -- that is production's exact
      failure mode (a worker running as a user without CAP_NET_ADMIN), and it
      is the thing this suite exists to catch. Fail, loudly.

    The fail-closed refusal has its own test below. It does not need this one.
    """
    try:
        return await DockerOciRuntime()._egress_network()  # noqa: SLF001
    except RuntimeUnavailable as refusal:
        if sys.platform != "linux":
            pytest.skip(f"no iptables on {sys.platform}; egress filtering is untestable here")
        pytest.fail(
            "this is a Linux host and the egress filter would not install, which is "
            "the condition that leaves networked artifacts unfiltered in production. "
            "Run privileged (CAP_NET_ADMIN), do not skip past it.\n"
            f"{refusal}"
        )


async def docker_cli(*args: str, check: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if check:
        assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


async def iptables(*args: str) -> int:
    """The host's firewall, reached without going through the code under test."""
    process = await asyncio.create_subprocess_exec(
        "iptables", *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return await process.wait()


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
    except RuntimeUnavailable as refusal:
        return str(refusal)


def assert_unreachable(outcome: SandboxResult | str) -> None:
    """The packet was dropped. Not "the run was refused" -- dropped.

    These two used to be interchangeable here, which is how a filter that had
    never installed anywhere passed its own tests for weeks.
    """
    assert not isinstance(outcome, str), (
        "the run was refused rather than filtered, so this proves nothing about "
        f"the DROP rules: {outcome}"
    )
    assert outcome.exit_code != 0, outcome.stdout
    assert outcome.status is not ExecutionStatus.SUCCEEDED
    assert b"reachable" not in outcome.stdout


async def test_cloud_metadata_is_unreachable_with_network_true(image: str, filtering: str) -> None:
    """169.254.169.254 is one HTTP GET away from the worker's IAM credentials."""
    outcome = await attempt(
        image,
        "import socket\n"
        "s = socket.create_connection(('169.254.169.254', 80), timeout=5)\n"
        "s.sendall(b'GET /latest/meta-data/iam/security-credentials/ HTTP/1.0\\r\\n\\r\\n')\n"
        "print('reachable', s.recv(64))\n",
    )
    assert_unreachable(outcome)


async def test_link_local_is_unreachable_with_network_true(image: str, filtering: str) -> None:
    """The whole 169.254.0.0/16 range, not just the address everyone knows."""
    outcome = await attempt(
        image,
        "import socket\n"
        "socket.create_connection(('169.254.170.2', 80), timeout=5)\n"
        "print('reachable')\n",
    )
    assert_unreachable(outcome)


async def test_the_hosts_own_gateway_is_unreachable_with_network_true(
    image: str, filtering: str
) -> None:
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


async def test_a_private_peer_is_unreachable_with_network_true(image: str, filtering: str) -> None:
    """The strong one: a real listener, on a real RFC1918 address, refused.

    Everything else here can pass on a laptop for the wrong reason -- nothing
    answers on 169.254.169.254 at home. This one puts a service that *does*
    answer on the same network as the sandbox, so the filter has to be what
    stops it.
    """
    network = filtering

    listener = await docker_cli(
        "run", "--rm", "--detach", f"--network={network}", image, "python", "-c", LISTENER
    )
    try:
        details = json.loads(await docker_cli("inspect", listener))
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
        await docker_cli("rm", "-f", listener, check=False)


async def test_a_rule_removed_behind_the_runtimes_back_is_reinstalled(
    filtering: str,
) -> None:
    """The rules are on the host, and `iptables -F` is one command away.

    A worker that remembered "installed" from its first run would keep putting
    containers on the bridge unfiltered for the rest of its life, silently. So
    the state is the check: delete the metadata DROP rule behind the runtime's
    back, and the next networked run has to notice and put it back before
    anything starts.
    """
    runtime = DockerOciRuntime()
    rule = egress_rule("DOCKER-USER", "169.254.0.0/16")
    assert await iptables("-w", "5", "-D", *rule) == 0, "the rule was not there to remove"
    assert await iptables("-w", "5", "-C", *rule) != 0, "the rule survived being removed"

    await runtime._egress_network()  # noqa: SLF001 - the second run

    assert await iptables("-w", "5", "-C", *rule) == 0, (
        "the metadata DROP rule was not reinstalled -- the filter is being "
        "remembered rather than verified, so a flushed host runs unfiltered"
    )


async def test_a_networked_run_is_refused_when_the_filter_cannot_be_installed(
    image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed. A control that switches itself off when it cannot run is not one."""
    monkeypatch.setattr("boobs_execution.docker_oci.shutil.which", lambda _: None)
    outcome = await attempt(image, "print('reachable')")
    assert isinstance(outcome, str)
    assert "refusing to run a networked artifact" in outcome
    assert "iptables -I DOCKER-USER 1 -i" in outcome  # it says how to fix it
