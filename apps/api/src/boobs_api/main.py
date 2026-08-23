"""FastAPI application.

The API never executes an artifact. It reads, ranks, records, and enqueues
(spec section 9).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from boobs_api.routes import router
from boobs_api.worker_routes import router as worker_router
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
    await dispose()


def _web_root() -> Path | None:
    """Locate apps/web, whether running from a checkout or the container."""
    here = Path(__file__).resolve()
    candidates = [Path.cwd() / "apps" / "web", *(p / "apps" / "web" for p in here.parents)]
    return next((path for path in candidates if (path / "index.html").is_file()), None)


def _mount_discovery_surface(app: FastAPI) -> None:
    """Serve the landing page and llms.txt from the API itself.

    Discovery is a product feature (spec section 14), and an agent that has the
    API host has everything: /llms.txt, /openapi.json and /docs all sit on one
    origin. Mounted last so it can never shadow a /v1 route.
    """
    root = _web_root()
    if root is None:
        log.info("discovery_surface_not_found", searched="apps/web")
        return
    app.mount("/", StaticFiles(directory=str(root), html=True), name="web")


def create_app() -> FastAPI:
    app = FastAPI(
        title="80085.ai",
        version="0.1.0",
        summary="Shared, evidence-backed memory of executable solutions for AI agents.",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(worker_router)
    _mount_discovery_surface(app)

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
