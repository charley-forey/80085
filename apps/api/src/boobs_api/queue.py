"""Queue boundary.

The API enqueues; the worker executes. The API process never touches the
Docker daemon and never runs artifact code (spec sections 9 and 15).
"""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from boobs_common.config import settings

QUEUE_NAME = "80085:executions"
EXECUTE_TASK = "execute_experience"

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings().redis_url)


async def pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings(), default_queue_name=QUEUE_NAME)
    return _pool


async def enqueue_execution(execution_id: str) -> None:
    queue = await pool()
    await queue.enqueue_job(EXECUTE_TASK, execution_id, _job_id=execution_id)


async def healthy() -> bool:
    try:
        queue = await pool()
        await queue.ping()
        return True
    except Exception:  # noqa: BLE001 - readiness probe reports, never raises
        return False


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
