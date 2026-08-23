"""Shared fixtures.

Integration, security and e2e tests run against the real services from
docker-compose. They are skipped -- loudly -- rather than mocked when those
services are not up: a mocked sandbox would prove nothing about isolation, and
a mocked database would prove nothing about tenant filtering.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = os.environ.get(
    "BOOBS_TEST_DATABASE_URL",
    "postgresql+asyncpg://boobs:boobs@localhost:55432/boobs_test",
)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, text=True).returncode == 0


@pytest.fixture(scope="session")
def docker() -> None:
    if not _docker_available():
        pytest.skip("docker daemon is not running (start Docker Desktop)")


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


TEST_REDIS = os.environ.get("BOOBS_TEST_REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture(scope="session", autouse=True)
def redis_url() -> str:
    """A dedicated Redis database, flushed once per session.

    The test database is dropped and recreated each session; a queue that
    survived from the previous session would hold jobs naming rows that no
    longer exist.
    """
    os.environ["REDIS_URL"] = TEST_REDIS
    try:
        import redis

        redis.Redis.from_url(TEST_REDIS).flushdb()
    except Exception:  # noqa: BLE001 - arq brings redis; if it is absent, carry on
        pass
    return TEST_REDIS


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


@pytest.fixture
async def api(database_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    """An httpx client bound to the app in-process, on the test database."""
    import httpx

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("BOOBS_BOOTSTRAP_TOKEN", "test-bootstrap")
    monkeypatch.setenv("BOOBS_EMBEDDER", os.environ.get("BOOBS_EMBEDDER", "auto"))

    from boobs_common.config import settings
    from boobs_schemas import db as database

    settings.cache_clear()
    database.engine.cache_clear()
    database.session_factory.cache_clear()

    from boobs_common import storage

    await storage.ensure_bucket()

    from boobs_api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Both pools are cached module-globals bound to this test's event loop;
    # leaving them open makes the next test fail on a closed loop.
    from boobs_api import queue

    await queue.close()
    await database.dispose()


@pytest.fixture(scope="session")
def worker(database_url: str, redis_url: str, docker: None) -> Iterator[subprocess.Popen[bytes]]:
    """A real arq worker process against the test database.

    Deliberately a separate process: an in-process shortcut would skip the
    queue and the sandbox, which are exactly the parts that must work.
    """
    log = ROOT / ".worker-test.log"
    handle = log.open("wb")
    # `sys.executable -m arq`, not `uv run arq`: on Windows terminating the
    # `uv run` wrapper orphans the worker, and an orphan pointed at a stale
    # database silently steals jobs from every later run.
    process = subprocess.Popen(
        [sys.executable, "-m", "arq", "boobs_worker.main.WorkerSettings"],
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env={**os.environ, "DATABASE_URL": database_url},
    )
    try:
        yield process
    finally:
        handle.close()
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def digests() -> dict[str, str]:
    import json

    path = ROOT / "capabilities" / "digests.json"
    if not path.is_file():
        pytest.skip("run `uv run python scripts/build_capabilities.py` first")
    return dict(json.loads(path.read_text()))
