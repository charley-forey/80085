"""Execution worker.

Runs wherever a container runtime exists -- a laptop, a VM, a CI box -- and
talks to 80085 over HTTPS only:

    lease a job -> run it in the sandbox -> report what happened

It holds one scoped API key. It has no database credentials, no queue
credentials, and no privileged path of any kind. It does not decide whether a
run succeeded either: it reports the raw result and the API verifies it.

    uv run 80085-worker
    BOOBS_API_URL=https://api.example BOOBS_API_KEY=sk_80085_... uv run 80085-worker
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import platform
import signal
import sys
from typing import Any

import httpx

from boobs_common.config import settings
from boobs_domain.enums import ExecutionStatus
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import DockerOciRuntime
from boobs_observability import configure, logger

log = logger(__name__)
runtime = DockerOciRuntime()

IDLE_SLEEP_SECONDS = 3.0
ERROR_SLEEP_SECONDS = 10.0
_stopping = asyncio.Event()


def worker_id() -> str:
    return os.environ.get("BOOBS_WORKER_ID") or f"{platform.node()}-{os.getpid()}"[:64]


def client() -> httpx.AsyncClient:
    key = os.environ.get("BOOBS_API_KEY", settings().boobs_api_key)
    if not key:
        raise SystemExit(
            "BOOBS_API_KEY is not set. A worker needs an API key with the "
            "'worker:execute' scope; mint one with scripts/create_worker_key.py."
        )
    return httpx.AsyncClient(
        base_url=os.environ.get("BOOBS_API_URL", settings().api_base_url),
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(120.0),
    )


async def run_job(job: dict[str, Any]) -> SandboxResult:
    limits = settings().sandbox
    request = SandboxRequest(
        execution_id=job["execution_id"],
        image=job["image"],
        command=list(job.get("command") or []),
        input_files={
            name: base64.b64decode(blob) for name, blob in (job.get("inputs") or {}).items()
        },
        cpu=limits.cpu,
        memory_mb=limits.memory_mb,
        tmpfs_mb=limits.tmpfs_mb,
        timeout_seconds=limits.timeout_seconds,
        pids=limits.pids,
        max_output_bytes=limits.max_output_bytes,
        network=bool(job.get("network")),
    )
    try:
        return await runtime.execute(request)
    except Exception as exc:  # noqa: BLE001 - a runtime failure is a failed run
        log.error("sandbox_error", execution_id=job["execution_id"], error=str(exc))
        return SandboxResult(
            status=ExecutionStatus.FAILED, exit_code=None, duration_ms=0, error=str(exc)
        )


async def report(http: httpx.AsyncClient, job: dict[str, Any], result: SandboxResult) -> None:
    response = await http.post(
        f"/v1/worker/executions/{job['execution_id']}/result",
        json={
            "worker_id": worker_id(),
            "status": str(result.status),
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "stdout": base64.b64encode(result.stdout).decode(),
            "stderr": base64.b64encode(result.stderr).decode(),
            "outputs": {
                name: base64.b64encode(blob).decode() for name, blob in result.output_files.items()
            },
            "truncated": result.truncated,
            "error": result.error,
        },
    )
    if response.status_code >= 400:
        log.error(
            "result_rejected",
            execution_id=job["execution_id"],
            code=response.status_code,
            detail=response.text[:300],
        )
        return
    body = response.json()
    log.info(
        "execution_finished",
        execution_id=job["execution_id"],
        status=body.get("status"),
        verified=body.get("verified"),
    )


async def loop() -> None:
    configure("80085-worker")
    identity = worker_id()
    async with client() as http:
        log.info("worker_started", worker_id=identity, api=str(http.base_url))
        while not _stopping.is_set():
            try:
                response = await http.post("/v1/worker/lease", json={"worker_id": identity})
                if response.status_code == 401:
                    raise SystemExit("API key rejected (401). Check BOOBS_API_KEY.")
                if response.status_code == 403:
                    raise SystemExit(
                        "API key lacks the 'worker:execute' scope (403). "
                        "Mint a worker key with scripts/create_worker_key.py."
                    )
                response.raise_for_status()
                job = response.json().get("job")
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001 - the API may be restarting
                log.warning("lease_failed", error=str(exc))
                await _sleep(ERROR_SLEEP_SECONDS)
                continue

            if job is None:
                await _sleep(IDLE_SLEEP_SECONDS)
                continue

            log.info("job_leased", execution_id=job["execution_id"], image=job["image"])
            result = await run_job(job)
            await report(http, job, result)


async def _sleep(seconds: float) -> None:
    """Sleep, but wake immediately on shutdown."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_stopping.wait(), seconds)


def main() -> None:
    def stop(*_: object) -> None:
        _stopping.set()

    with contextlib.suppress(NotImplementedError, ValueError):
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        pass
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
