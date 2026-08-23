"""Shared fixtures.

Integration, security and e2e tests run against the real services from
docker-compose. They are skipped -- loudly -- rather than mocked when those
services are not up: a mocked sandbox would prove nothing about isolation, and
a mocked database would prove nothing about tenant filtering.

The API runs as a real uvicorn process rather than through an ASGI transport,
because the worker is an HTTPS client and needs a socket to talk to.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_TOKEN = "test-bootstrap"
TEST_DATABASE = os.environ.get(
    "BOOBS_TEST_DATABASE_URL",
    "postgresql+asyncpg://boobs:boobs@localhost:55432/boobs_test",
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, text=True).returncode == 0


@pytest.fixture(scope="session")
def docker() -> None:
    if not _docker_available():
        pytest.skip("docker daemon is not running (start Docker Desktop)")


@pytest.fixture(scope="session")
def database_url() -> str:
    """Create and migrate a dedicated test database.

    Uses asyncpg directly -- it is already a dependency, so the test harness
    does not drag in a second driver just to issue two DDL statements.
    """
    import asyncpg

    dsn = TEST_DATABASE.replace("+asyncpg", "")
    admin_dsn, name = dsn.rsplit("/", 1)

    async def recreate() -> None:
        connection = await asyncpg.connect(f"{admin_dsn}/postgres")
        try:
            await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    try:
        asyncio.run(recreate())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres is not reachable ({exc}); run `docker compose up -d`")

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE},
    )
    if result.returncode != 0:
        pytest.fail("migrations failed\n" + result.stdout + result.stderr)
    return TEST_DATABASE


@pytest.fixture(scope="session")
def api_url(database_url: str) -> Iterator[str]:
    """A real uvicorn process on a free port, against the test database."""
    import httpx

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = ROOT / ".test-api.log"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "boobs_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "DATABASE_URL": database_url,
            "BOOBS_BOOTSTRAP_TOKEN": BOOTSTRAP_TOKEN,
        },
    )

    healthy = False
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            pytest.fail("api process exited:\n" + log_path.read_text(errors="replace"))
        try:
            if httpx.get(f"{url}/v1/health", timeout=2.0).status_code == 200:
                healthy = True
                break
        except Exception:  # noqa: BLE001 - still starting
            time.sleep(0.5)
    if not healthy:
        process.terminate()
        log.close()
        pytest.fail("api did not become healthy:\n" + log_path.read_text(errors="replace"))

    try:
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


@pytest.fixture
async def api(api_url: str) -> AsyncIterator[Any]:
    import httpx

    async with httpx.AsyncClient(base_url=api_url, timeout=300.0) as client:
        yield client


def bootstrap_sync(
    api_url: str, organization: str, agent: str, scopes: list[str] | None = None
) -> dict[str, Any]:
    import httpx

    payload: dict[str, Any] = {
        "organization": organization,
        "agent": agent,
        "token": BOOTSTRAP_TOKEN,
    }
    if scopes is not None:
        payload["scopes"] = scopes
    response = httpx.post(f"{api_url}/v1/bootstrap", json=payload, timeout=60.0)
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.fixture(scope="session")
def worker_key(api_url: str) -> str:
    """A key with only the worker scope -- it cannot read or record anything."""
    from boobs_security.keys import Scope

    return str(bootstrap_sync(api_url, "test-workers", "test-worker", [Scope.WORKER])["api_key"])


@pytest.fixture(scope="session")
def worker(api_url: str, worker_key: str, docker: None) -> Iterator[subprocess.Popen[bytes]]:
    """A real worker process leasing jobs over HTTP.

    Deliberately a separate process: an in-process shortcut would skip the
    queue and the sandbox, which are exactly the parts that must work.
    """
    log = (ROOT / ".test-worker.log").open("wb")
    # `sys.executable -m ...`, not `uv run ...`: on Windows, terminating the
    # `uv run` wrapper orphans the child, and an orphaned worker keeps leasing
    # jobs from every later run.
    process = subprocess.Popen(
        [sys.executable, "-m", "boobs_worker.main"],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "BOOBS_API_URL": api_url,
            "BOOBS_API_KEY": worker_key,
            "BOOBS_WORKER_ID": "pytest-worker",
        },
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Any]:
    """A session against the test database, for the few tests that assert on
    database-level behaviour (triggers, leasing) rather than API behaviour."""
    os.environ["DATABASE_URL"] = database_url

    from boobs_common.config import settings
    from boobs_schemas import db as database

    settings.cache_clear()
    database.engine.cache_clear()
    database.session_factory.cache_clear()

    async with database.session() as session:
        yield session
    await database.dispose()


@pytest.fixture(scope="session")
def digests() -> dict[str, str]:
    path = ROOT / "capabilities" / "digests.json"
    if not path.is_file():
        pytest.skip("run `uv run python scripts/build_capabilities.py` first")
    return dict(json.loads(path.read_text()))
