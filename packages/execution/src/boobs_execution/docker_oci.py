"""Docker OCI sandbox -- the entire security surface (spec sections 15 and 16).

Every artifact is hostile until proven otherwise. The container therefore gets:
no network, no capabilities, no privilege escalation, a read-only root
filesystem, a non-root user, bounded cpu/memory/pids/time, and no host mounts
or sockets of any kind. Inputs and outputs move as tar streams through
`docker cp`, which is why no bind mount is needed.

The image is always referenced by digest. A tag would let the bytes change
under a version that evidence was collected for, which would make every
success rate in the system a lie.

An Experience may declare that it needs the network, and that declaration is
made by its own author with nobody approving it. `--network=bridge` would
therefore be an attacker-chosen flag that reaches the cloud metadata service,
the worker's own LAN, and everything else routable from the host. So a
networked run does not get the default bridge: it gets a dedicated network
whose traffic is filtered by the host firewall, and the destinations that
matter -- link-local, metadata, loopback, RFC1918 -- are refused whatever the
flag says. If the filter cannot be installed, the run is refused rather than
run unfiltered -- and it is re-verified before every networked run, because
the rules live on the host where anything can flush them.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import tarfile
import time
from collections.abc import Sequence

from boobs_common.errors import ExecutionFailed
from boobs_domain.entities import OCI_PINNED_RE
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult


async def _reap(process: asyncio.subprocess.Process) -> None:
    """Terminate a docker CLI process without caring whether it already exited."""
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with contextlib.suppress(TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), 30)


WORKDIR = "/work"
PULL_TIMEOUT = 300
DOCKER = "docker"

# A networked sandbox never joins the default bridge, because the filter below
# is pinned to one interface and the default bridge carries everything else on
# the host too. The bridge name must fit the kernel's 15-character limit.
EGRESS_NETWORK = "80085-egress"
EGRESS_BRIDGE = "br-80085egress"
BRIDGE_NAME_OPT = "com.docker.network.bridge.name"

# Where a networked artifact must never be able to send a packet, whoever
# recorded it. Everything here is either the host's own neighbourhood or an
# address that means something private to the machine the worker runs on.
BLOCKED_DESTINATIONS = (
    "169.254.0.0/16",  # link-local, and 169.254.169.254 is every cloud's IAM credentials
    "127.0.0.0/8",  # the host's loopback, via a martian route
    "10.0.0.0/8",  # RFC1918
    "172.16.0.0/12",  # RFC1918, and Docker's own default address pools
    "192.168.0.0/16",  # RFC1918
    "100.64.0.0/10",  # carrier NAT, and several clouds' internal fabric
    "192.0.0.0/24",  # IETF protocol assignments
    "198.18.0.0/15",  # benchmarking range, routed internally by some hosts
    "224.0.0.0/4",  # multicast
    "240.0.0.0/4",  # reserved
)

# DOCKER-USER is the chain Docker guarantees it evaluates before its own rules
# and never flushes; it sees forwarded traffic, which is everything leaving the
# bridge. INPUT is the other half: a packet addressed to the host itself is
# delivered locally and never reaches FORWARD, so blocking only DOCKER-USER
# would leave every service on the worker reachable from inside the sandbox.
FILTERED_CHAINS = ("DOCKER-USER", "INPUT")
IPTABLES = "iptables"


def egress_rule(chain: str, destination: str) -> list[str]:
    """One firewall rule, as arguments after the -C/-I verb."""
    return [chain, "-i", EGRESS_BRIDGE, "-d", destination, "-j", "DROP"]


def egress_rules() -> list[list[str]]:
    return [egress_rule(chain, cidr) for chain in FILTERED_CHAINS for cidr in BLOCKED_DESTINATIONS]


def manual_egress_setup() -> str:
    """The rules an operator can install by hand, for the error message.

    A worker that cannot run `iptables` is a normal deployment (unprivileged
    user, Docker Desktop, a daemon on another machine). Telling it "refused"
    without telling it what to install is how a security control gets turned
    off instead of fixed.
    """
    lines = [f"docker network create --opt {BRIDGE_NAME_OPT}={EGRESS_BRIDGE} {EGRESS_NETWORK}"]
    lines += [" ".join([IPTABLES, "-I", *rule[:1], "1", *rule[1:]]) for rule in egress_rules()]
    return "\n  ".join(lines)


def _refusal(reason: str) -> str:
    """Why a networked run was refused, and how to make it possible."""
    return (
        f"refusing to run a networked artifact: {reason}. Unfiltered, the "
        "container reaches cloud metadata (169.254.169.254) and the worker's "
        "own private network, and the flag that asked for the network was set "
        "by the artifact's author. Install the filter once, as root:\n  " + manual_egress_setup()
    )


async def _iptables(*args: str) -> int:
    """Run iptables and report only whether it worked.

    ponytail: shells out to the host's iptables, so the worker needs
    CAP_NET_ADMIN (root, in practice) and a Linux Docker host. Upgrade path
    when that is too much: install these rules once at provisioning time, or
    put an egress proxy on the network and drop everything else.
    """
    process = await asyncio.create_subprocess_exec(
        IPTABLES,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), 30)
        return process.returncode or 0
    await _reap(process)
    return 1


class DockerOciRuntime:
    """ExecutionRuntime backed by the local Docker daemon.

    Firecracker, gVisor, Kata or WASI replace this class and nothing else:
    callers only know the `ExecutionRuntime` protocol.
    """

    def __init__(self, docker: str = DOCKER) -> None:
        self._docker = docker

    async def execute(self, request: SandboxRequest) -> SandboxResult:
        if not OCI_PINNED_RE.match(request.image):
            raise ExecutionFailed(
                f"refusing to execute unpinned image {request.image!r}; "
                "a digest reference is required"
            )

        await self._pull(request.image)
        container = await self._create(request)
        started = time.monotonic()
        try:
            if request.input_files:
                await self._copy_in(container, request.input_files)
            status, exit_code, stdout, stderr, truncated = await self._run(container, request)
            duration_ms = int((time.monotonic() - started) * 1000)
            outputs: dict[str, bytes] = {}
            if status is ExecutionStatus.SUCCEEDED:
                outputs = await self._copy_out(
                    container, skip=set(request.input_files), limit=request.max_output_bytes
                )
            return SandboxResult(
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                output_files=outputs,
                truncated=truncated,
            )
        finally:
            # -v removes the anonymous work volume with the container.
            await self._docker_run("rm", "-f", "-v", container, check=False)

    # ------------------------------------------------------------------ docker

    async def _docker_run(
        self,
        *args: str,
        check: bool = True,
        timeout: int | None = 60,
        stdin: bytes | None = None,
    ) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            self._docker,
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
        except TimeoutError:
            await _reap(process)
            raise
        if check and process.returncode != 0:
            detail = stderr.decode(errors="replace")[:500]
            raise ExecutionFailed(f"docker {args[0]} failed ({process.returncode}): {detail}")
        return process.returncode or 0, stdout, stderr

    async def _pull(self, image: str) -> None:
        await self._docker_run("pull", "--quiet", image, timeout=PULL_TIMEOUT)

    def _create_args(self, request: SandboxRequest, network: str) -> Sequence[str]:
        args = [
            "create",
            "--rm=false",
            f"--name=80085-{request.execution_id}",
            f"--label=80085.execution_id={request.execution_id}",
            # Isolation
            f"--network={network}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            # Resource limits
            f"--cpus={request.cpu}",
            f"--memory={request.memory_mb}m",
            f"--memory-swap={request.memory_mb}m",  # no swap escape hatch
            f"--pids-limit={request.pids}",
            f"--tmpfs=/tmp:rw,noexec,nosuid,size={request.tmpfs_mb}m",
            # Writable working directory that survives docker cp before start.
            # ponytail: still an anonymous volume, so nothing bounds the size of
            # /work and a hostile artifact can fill the worker's disk. Neither
            # obvious fix works on a stock Docker host: a tmpfs-backed local
            # volume is unmounted between `docker cp` and `start` (refcount
            # zero) and loses the inputs, and `--storage-opt size=` needs
            # devicemapper, btrfs, zfs or xfs project quotas rather than the
            # overlay2 everyone actually runs. So the only bound is the wall
            # clock -- which is exactly why the longer execution tiers are
            # granted by an operator instead of being self-serve. Upgrade path:
            # a quota-enabled volume driver, or a per-execution loopback
            # filesystem mounted by the operator, not by this process.
            "-v",
            WORKDIR,
            f"--workdir={WORKDIR}",
        ]
        for key, value in request.env.items():
            args.append(f"--env={key}={value}")
        args.append(request.image)
        args.extend(request.command)
        return args

    async def _create(self, request: SandboxRequest) -> str:
        # No network at all is the default and needs no filter. A run that asks
        # for the network gets the filtered network or does not run.
        network = await self._egress_network() if request.network else "none"
        _, stdout, _ = await self._docker_run(*self._create_args(request, network))
        return stdout.decode().strip()

    # ------------------------------------------------------------------ egress

    async def _egress_network(self) -> str:
        """Verified before every networked run, never remembered.

        Remembering it was the bug. The rules live on the host, not in this
        process, and anything on the host can remove them -- `iptables -F`, a
        package upgrade, a firewall tool, a daemon restart that drops custom
        chains. A worker that latched "installed" at the first run would then
        keep serving networked containers completely unfiltered for the rest of
        its life, with no error and nothing in the logs to notice.

        So the check is the state. `iptables -C` is idempotent and already how
        this decides whether to install anything, so re-checking costs a sweep
        of it: **58 ms median** for the twenty rules (2.9 ms each, n=20 sweeps,
        measured in a privileged Linux netns), plus one `docker network
        inspect` at roughly 75 ms. Call it 135 ms against a run that pulls,
        creates, copies a tar in, and then executes for up to an hour. Nothing
        here is worth a TTL: a cache with a window is a window in which the
        filter is gone and we are still saying it is there.
        """
        await self._ensure_egress_network()
        await self._ensure_egress_filter()
        return EGRESS_NETWORK

    async def _ensure_egress_network(self) -> None:
        """A dedicated bridge, so the filter can name one interface."""
        code, stdout, _ = await self._docker_run("network", "inspect", EGRESS_NETWORK, check=False)
        if code != 0:
            await self._docker_run(
                "network",
                "create",
                f"--opt={BRIDGE_NAME_OPT}={EGRESS_BRIDGE}",
                EGRESS_NETWORK,
                check=False,  # another worker may have won the race
            )
            _, stdout, _ = await self._docker_run("network", "inspect", EGRESS_NETWORK)
        options = json.loads(stdout)[0].get("Options") or {}
        if options.get(BRIDGE_NAME_OPT) != EGRESS_BRIDGE:
            raise ExecutionFailed(
                _refusal(
                    f"the {EGRESS_NETWORK} network exists but is not on {EGRESS_BRIDGE}, "
                    "so the filter would not cover it"
                )
            )

    async def _ensure_egress_filter(self) -> None:
        """Install the DROP rules, or refuse the run.

        Fail closed on purpose. Every other outcome here -- no iptables, no
        privileges, a chain that is not there -- ends with a container that can
        read the host's IAM credentials, and a control that quietly turns
        itself off under those conditions is not a control.
        """
        if shutil.which(IPTABLES) is None:
            raise ExecutionFailed(_refusal(f"{IPTABLES} is not on PATH"))
        for rule in egress_rules():
            if await _iptables("-w", "5", "-C", *rule) == 0:
                continue
            if await _iptables("-w", "5", "-I", rule[0], "1", *rule[1:]) != 0:
                joined = " ".join(rule)
                raise ExecutionFailed(_refusal(f"could not install: {IPTABLES} -I {joined}"))

    async def _copy_in(self, container: str, files: dict[str, bytes]) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mode = 0o644
                info.uid = info.gid = 65534
                archive.addfile(info, io.BytesIO(content))
        await self._docker_run("cp", "-", f"{container}:{WORKDIR}", stdin=buffer.getvalue())

    async def _run(
        self, container: str, request: SandboxRequest
    ) -> tuple[ExecutionStatus, int | None, bytes, bytes, bool]:
        process = await asyncio.create_subprocess_exec(
            self._docker,
            "start",
            "--attach",
            container,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), request.timeout_seconds)
        except TimeoutError:
            # Kill the container first; the attached client then exits on its
            # own, so the client may already be gone by the time we reap it.
            await self._docker_run("kill", container, check=False, timeout=30)
            await _reap(process)
            return ExecutionStatus.TIMEOUT, None, b"", b"", False

        cap = request.max_output_bytes
        truncated = len(stdout) > cap or len(stderr) > cap
        exit_code = process.returncode
        status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
        return status, exit_code, stdout[:cap], stderr[:cap], truncated

    async def _copy_out(self, container: str, skip: set[str], limit: int) -> dict[str, bytes]:
        try:
            _, stream, _ = await self._docker_run("cp", f"{container}:{WORKDIR}/.", "-")
        except ExecutionFailed:
            return {}

        outputs: dict[str, bytes] = {}
        total = 0
        with tarfile.open(fileobj=io.BytesIO(stream), mode="r") as archive:
            for member in archive:
                name = member.name.lstrip("./")
                if not member.isfile() or not name or name in skip:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                content = extracted.read(limit - total + 1)
                total += len(content)
                if total > limit:
                    break
                outputs[name] = content
        return outputs
