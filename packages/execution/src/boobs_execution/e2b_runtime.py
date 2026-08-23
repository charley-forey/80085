"""E2B sandbox -- the same contract, on a stronger boundary.

Docker gives every run a share of the host kernel. E2B gives every run a
Firecracker microVM, so a kernel bug in an artifact buys the attacker a
disposable VM rather than the machine the worker runs on. DECISIONS 10 named
E2B as the undo path for "the worker runs on a host with Docker", and this is
that undo: with `BOOBS_RUNTIME=e2b` a worker needs no local Docker daemon at
all, so execution no longer depends on one laptop staying awake.

What deliberately does **not** carry over from `docker_oci`: `--cap-drop`,
`--security-opt no-new-privileges`, `--read-only` and uid 65534. Those exist
because Docker shares the host kernel with the artifact; here the guest kernel
*is* the sandbox and there is nothing else inside it to protect. The limits
that still mean something -- wall clock and output size -- are enforced here,
and the image is still refused unless it is pinned by digest (DECISIONS 13):
if the bytes could change under a version, every
success rate in the system would be a lie.

What this runtime does **not** enforce, said out loud rather than implied:
`cpu`, `memory_mb`, `tmpfs_mb` and `pids` are cgroup flags with no E2B
equivalent (DECISIONS 19), and the network is not isolated at all, which is
why `execute` refuses `network: false` outright (DECISIONS 27). A networked
run gets no destination filter either -- `allow_internet_access` is a boolean
-- so the link-local and RFC1918 drops `docker_oci` installs (DECISIONS 25)
have no counterpart here.

E2B runs *templates*, not registry references, so the pinned image is turned
into a template once per digest and reused. The template's identity is
derived from the reference, which contains the digest, so a different digest
can never resolve to the same template.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shlex
import time
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from boobs_common.errors import ExecutionFailed, RuntimeUnavailable
from boobs_domain.entities import OCI_PINNED_RE
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from e2b import AsyncSandbox

WORKDIR = "/work"
API_KEY_ENV = "E2B_API_KEY"
# The artifact registry is authenticated, and E2B builds the template on its
# own machines -- so the credential has to travel with the build request or
# every pull of a private artifact fails with an unhelpful 401.
REGISTRY_USER_ENV = "BOOBS_REGISTRY_USERNAME"
REGISTRY_PASSWORD_ENV = "BOOBS_REGISTRY_PASSWORD"  # noqa: S105 - the variable name, not a password
# The sandbox must outlive the command it runs, or E2B reclaims the VM while
# we are still reading outputs out of it.
LIFETIME_SLACK_SECONDS = 60


def api_key() -> str:
    """The E2B credential, from the environment and nowhere else.

    Never defaulted and never written to a file: a key in source is a key in
    every clone, every image layer and every log of the build that copied it.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeUnavailable(
            f"{API_KEY_ENV} is not set. The E2B runtime needs an E2B API key; "
            "export it, or run with BOOBS_RUNTIME=docker to use local Docker."
        )
    return key


def registry_credentials() -> tuple[str | None, str | None]:
    """Registry username and password, or a pair of Nones for a public one.

    Both or neither: a username with no password is a misconfiguration that
    would otherwise surface as an authentication failure inside E2B's builder,
    where nobody can see it. Read from the environment for the same reason the
    E2B key is -- a credential in source is a credential in every clone.
    """
    user = os.environ.get(REGISTRY_USER_ENV, "").strip()
    password = os.environ.get(REGISTRY_PASSWORD_ENV, "").strip()
    if bool(user) != bool(password):
        raise RuntimeUnavailable(
            f"set both {REGISTRY_USER_ENV} and {REGISTRY_PASSWORD_ENV}, or neither: "
            "half a credential cannot authenticate to the artifact registry."
        )
    return (user or None, password or None)


def staged_name(name: str) -> str:
    """Reject an input filename that would write outside the work directory.

    The API already refuses these (`ExecuteRequest.inputs`), so this is the
    second lock on the same door -- the runtime is handed filenames by a
    caller it does not trust and should not depend on someone else's
    validation to stay inside `/work`.
    """
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not name or name.startswith("/") or ".." in parts:
        raise ExecutionFailed(f"refusing input file {name!r}: it escapes {WORKDIR}")
    return name


class E2BRuntime:
    """ExecutionRuntime backed by E2B's Firecracker microVMs.

    Callers only know the `ExecutionRuntime` protocol, so selecting this
    instead of `DockerOciRuntime` changes nothing above it.
    """

    def __init__(self, workdir: str = WORKDIR) -> None:
        self._workdir = workdir
        # ponytail: templates are built on first use and remembered for the
        # life of the process, so every worker restart pays one build per
        # digest it sees. Upgrade path when that hurts: build templates in CI
        # when the artifact is registered and store the template id on the
        # artifact row, so the worker only ever creates sandboxes.
        self._templates: dict[str, str] = {}
        self._build_lock = asyncio.Lock()

    async def execute(self, request: SandboxRequest) -> SandboxResult:
        if not OCI_PINNED_RE.match(request.image):
            raise ExecutionFailed(
                f"refusing to execute unpinned image {request.image!r}; "
                "a digest reference is required"
            )
        if not request.command:
            raise ExecutionFailed(
                "the E2B runtime needs an explicit command; it cannot fall back "
                "to the image entrypoint the way Docker does"
            )

        # Measured, not assumed: with allow_internet_access=False, and again
        # with network={"deny_out": ["0.0.0.0/0"]}, a sandbox on this account
        # still opened a TCP connection to 1.1.1.1:53. DNS is refused, which
        # hides it -- a resolver failure looks like no network until something
        # dials an address directly.
        #
        # `--network=none` is the first row of the table in docs/security.md
        # and the thing that stops exfiltration, C2 and mining. A runtime that
        # cannot deliver it must not pretend to: an artifact is assumed
        # hostile, and quietly handing a hostile artifact the internet because
        # a vendor flag was ignored is the worst failure this system has.
        #
        # So refuse. E2B stays usable for artifacts that legitimately declare
        # network access, where the guarantee was never claimed.
        if not request.network:
            raise RuntimeUnavailable(
                "the E2B runtime cannot enforce an isolated network: "
                "allow_internet_access=False and deny_out=0.0.0.0/0 were both "
                "observed to leave outbound TCP open, so a no-network artifact "
                "would run with the internet reachable. Use BOOBS_RUNTIME=docker "
                "for these, which enforces --network=none and is covered by "
                "tests/security/test_sandbox.py."
            )

        inputs = {staged_name(name): blob for name, blob in request.input_files.items()}
        from e2b import AsyncSandbox  # imported lazily: a hosted runtime is optional

        template = await self._template(request.image)
        started = time.monotonic()
        sandbox = await AsyncSandbox.create(
            template=template,
            timeout=request.timeout_seconds + LIFETIME_SLACK_SECONDS,
            allow_internet_access=request.network,
            api_key=api_key(),
        )
        try:
            for name, content in inputs.items():
                await sandbox.files.write(f"{self._workdir}/{name}", content)
            status, exit_code, stdout, stderr, truncated = await self._run(sandbox, request)
            duration_ms = int((time.monotonic() - started) * 1000)
            outputs: dict[str, bytes] = {}
            if status is ExecutionStatus.SUCCEEDED:
                outputs = await self._collect(
                    sandbox, skip=set(inputs), limit=request.max_output_bytes
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
            with contextlib.suppress(Exception):
                await sandbox.kill()

    # ---------------------------------------------------------------- template

    async def _template(self, image: str) -> str:
        """Build (or reuse) the E2B template for one pinned image."""
        name = "80085-" + hashlib.sha256(image.encode()).hexdigest()[:32]
        async with self._build_lock:
            known = self._templates.get(name)
            if known is not None:
                return known
            from e2b import AsyncTemplate, Template

            user, password = registry_credentials()
            built = await AsyncTemplate.build(
                Template()
                .from_image(image, username=user, password=password)
                # The artifact contract promises a writable /work. Build steps
                # do not run as root, so shelling out to mkdir got permission
                # denied at `/` and failed the whole build; make_dir takes the
                # user explicitly and says what it means. 1777 because the
                # sandbox command runs as a different user again, and the
                # sticky bit keeps that widening from being a way to clobber
                # someone else's file.
                .make_dir(self._workdir, mode=0o1777, user="root")
                .set_workdir(self._workdir),
                name=name,
                api_key=api_key(),
            )
            self._templates[name] = built.template_id
            return built.template_id

    # ----------------------------------------------------------------- sandbox

    async def _run(
        self, sandbox: AsyncSandbox, request: SandboxRequest
    ) -> tuple[ExecutionStatus, int | None, bytes, bytes, bool]:
        from e2b import CommandExitException, TimeoutException

        result: Any
        try:
            result = await sandbox.commands.run(
                shlex.join(request.command),
                cwd=self._workdir,
                envs=dict(request.env),
                timeout=request.timeout_seconds,
                request_timeout=request.timeout_seconds + LIFETIME_SLACK_SECONDS,
            )
        except CommandExitException as exc:
            # A non-zero exit is a result, not an error: the floor verifier
            # believes the exit code, so it has to reach the caller.
            result = exc
        except TimeoutException:
            return ExecutionStatus.TIMEOUT, None, b"", b"", False

        stdout = result.stdout.encode()
        stderr = result.stderr.encode()
        cap = request.max_output_bytes
        truncated = len(stdout) > cap or len(stderr) > cap
        exit_code = int(result.exit_code)
        status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
        return status, exit_code, stdout[:cap], stderr[:cap], truncated

    async def _collect(self, sandbox: AsyncSandbox, skip: set[str], limit: int) -> dict[str, bytes]:
        from e2b import FileType

        prefix = self._workdir.rstrip("/") + "/"
        entries = await sandbox.files.list(self._workdir, depth=None)
        outputs: dict[str, bytes] = {}
        total = 0
        for entry in sorted(entries, key=lambda item: item.path):
            name = entry.path.removeprefix(prefix)
            if entry.type is not FileType.FILE or not name or name in skip:
                continue
            # Size first: reading a multi-gigabyte output into memory just to
            # discover it breaches the cap would be its own denial of service.
            if total + entry.size > limit:
                break
            outputs[name] = bytes(await sandbox.files.read(entry.path, format="bytes"))
            total += entry.size
        return outputs
