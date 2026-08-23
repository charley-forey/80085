"""Docker OCI sandbox -- the entire security surface (spec sections 15 and 16).

Every artifact is hostile until proven otherwise. The container therefore gets:
no network, no capabilities, no privilege escalation, a read-only root
filesystem, a non-root user, bounded cpu/memory/pids/time, and no host mounts
or sockets of any kind. Inputs and outputs move as tar streams through
`docker cp`, which is why no bind mount is needed.

The image is always referenced by digest. A tag would let the bytes change
under a version that evidence was collected for, which would make every
success rate in the system a lie.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
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

    def _create_args(self, request: SandboxRequest) -> Sequence[str]:
        args = [
            "create",
            "--rm=false",
            f"--name=80085-{request.execution_id}",
            f"--label=80085.execution_id={request.execution_id}",
            # Isolation
            "--network=none" if not request.network else "--network=bridge",
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
            # ponytail: anonymous volume, so tmpfs size limits do not apply to
            # /work. Upgrade path if disk abuse matters: a quota-enabled volume
            # driver, or --storage-opt size= on a driver that supports it.
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
        _, stdout, _ = await self._docker_run(*self._create_args(request))
        return stdout.decode().strip()

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
