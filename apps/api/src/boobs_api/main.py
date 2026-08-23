"""FastAPI application.

The API never executes an artifact. It reads, ranks, records, and enqueues
(spec section 9).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from boobs_api import queue
from boobs_api.routes import router
from boobs_common import storage
from boobs_common.errors import (
    Conflict,
    EightyKError,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationError,
)
from boobs_observability import configure, logger
from boobs_schemas.db import dispose

STATUS_FOR = {
    Unauthorized: 401,
    Forbidden: 403,
    NotFound: 404,
    Conflict: 409,
    ValidationError: 422,
}

log = logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure("80085-api")
    try:
        await storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001 - startup must not depend on S3
        log.warning("object_storage_unavailable_at_startup", error=str(exc))
    yield
    await queue.close()
    await dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="80085.ai",
        version="0.1.0",
        summary="Shared, evidence-backed memory of executable solutions for AI agents.",
        lifespan=lifespan,
    )
    app.include_router(router)

    @app.exception_handler(EightyKError)
    async def domain_error(_: Request, exc: EightyKError) -> JSONResponse:
        code = next((status for kind, status in STATUS_FOR.items() if isinstance(exc, kind)), 500)
        if code >= 500:
            log.error("unhandled_domain_error", error=str(exc), kind=type(exc).__name__)
        return JSONResponse(
            status_code=code, content={"error": type(exc).__name__, "detail": str(exc)}
        )

    return app


app = create_app()
