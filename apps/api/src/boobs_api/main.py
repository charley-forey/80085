"""FastAPI application.

The API never executes an artifact. It reads, ranks, records, and enqueues
(spec section 9).
"""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from boobs_api.limits import RateLimited, client_ip
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
from boobs_observability import configure, instrument_fastapi, logger
from boobs_schemas.db import dispose

STATUS_FOR = {
    Unauthorized: 401,
    Forbidden: 403,
    NotFound: 404,
    Conflict: 409,
    ValidationError: 422,
    RateLimited: 429,
}

log = logger(__name__)

# The licence and corpus terms are served from the site, which copies them out
# of the repository root at build time. Both hosts serve apps/web/public, so
# this one origin answers for either.
SITE = "https://80085.ai"

# The ANSI representation is text. Left unregistered it is served as
# application/octet-stream, which invites a client to download `curl 80085.ai`
# rather than print it.
mimetypes.add_type("text/plain", ".ansi")


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
    """Locate the built site, whether running from a checkout or the container.

    apps/web/public is build output, not source: `node build.mjs` renders it
    from apps/web/content.js. If it is absent the surface is simply not
    mounted, which is why this returns None rather than raising -- the API is
    perfectly useful without a landing page attached to it.
    """
    here = Path(__file__).resolve()
    rel = Path("apps") / "web" / "public"
    candidates = [Path.cwd() / rel, *(p / rel for p in here.parents)]
    return next((path for path in candidates if (path / "p" / "home.html").is_file()), None)


# Representations of the same URL, chosen by what the client says it wants.
# These mirror the rewrite table in apps/web/vercel.json; both are generated
# from the same content, so the two hosts answer identically.
_AGENTS = (
    "ClaudeBot",
    "Claude-User",
    "Claude-SearchBot",
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "Bytespider",
    "CCBot",
    "Applebot-Extended",
    "cohere-ai",
    "Meta-ExternalAgent",
)
_SHELLS = ("curl", "wget", "httpie", "libcurl")
# Not "index": a file called index.md is a directory index to a static
# host, which answers "/" from the filesystem before any negotiation runs.
_NEGOTIABLE = {"/": "home", "/install": "install"}


def _representation(path: str, accept: str, agent: str, fmt: str | None) -> str | None:
    """Which file answers this request, or None if this path is not negotiated.

    The HTML pages live under /p/ rather than at the paths they are served
    from, because on a static host an index.html at the root answers "/"
    before any negotiation rule gets to run. Keeping both hosts on the same
    layout is what lets them answer identically.
    """
    stem = _NEGOTIABLE.get(path.rstrip("/") or "/")
    if stem is None:
        return None
    page = f"/p/{stem}.html"
    if fmt in {"md", "txt"}:
        return f"/{stem}.{fmt}"
    lowered = agent.lower()
    if any(shell in lowered for shell in _SHELLS):
        return f"/{stem}.ansi"
    if any(bot.lower() in lowered for bot in _AGENTS):
        return f"/{stem}.md"
    if "text/markdown" in accept:
        return f"/{stem}.md"
    if "text/plain" in accept and "text/html" not in accept:
        return f"/{stem}.txt"
    return page


def _mount_discovery_surface(app: FastAPI) -> None:
    """Serve the landing page and llms.txt from the API itself.

    Discovery is a product feature (spec section 14), and an agent that has the
    API host has everything: /llms.txt, /openapi.json and /docs all sit on one
    origin. Mounted last so it can never shadow a /v1 route.
    """
    root = _web_root()
    if root is None:
        log.info("discovery_surface_not_found", searched="apps/web/public")
        return

    @app.middleware("http")
    async def negotiate(request: Request, call_next: Any) -> Any:
        """Serve the representation the caller asked for, from the same URL.

        A browser gets the page, `curl` gets ANSI, an agent gets markdown. The
        product is infrastructure for agents, so a site only legible to humans
        would undercut the pitch before anyone read a word.
        """
        if request.method in {"GET", "HEAD"}:
            target = _representation(
                request.url.path,
                request.headers.get("accept", ""),
                request.headers.get("user-agent", ""),
                request.query_params.get("format"),
            )
            if target and (root / target.lstrip("/")).is_file():
                request.scope["path"] = target
        response = await call_next(request)
        # Without this a CDN or proxy may hand one caller's representation to
        # the next caller. It is the likeliest way this breaks in production.
        response.headers["Vary"] = "Accept, User-Agent"
        return response

    app.mount("/", StaticFiles(directory=str(root), html=True), name="web")


def create_app() -> FastAPI:
    app = FastAPI(
        title="80085.ai",
        version="0.1.0",
        summary="Shared, evidence-backed memory of executable solutions for AI agents.",
        lifespan=lifespan,
        # Two assets, two instruments: ELv2 covers the code in the repository,
        # TERMS.md covers the corpus this API serves. An agent that reads only
        # openapi.json still gets told which is which.
        license_info={"name": "Elastic License 2.0 (code)", "url": f"{SITE}/LICENSE"},
        terms_of_service=f"{SITE}/TERMS.md",
    )
    app.include_router(router)
    app.include_router(worker_router)

    # Instrumented here rather than in lifespan: Starlette builds its
    # middleware stack before the lifespan runs, so adding middleware there
    # raises. This is a no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set.
    instrument_fastapi(app)

    @app.middleware("http")
    async def advertise_terms(request: Request, call_next: Any) -> Any:
        """Attach the licence terms to every response, machine-readably.

        Recall needs no key, so for most callers there is no signup step at
        which to show them anything. RFC 8288 link relations are the one notice
        channel that reaches an agent which only ever speaks HTTP.
        """
        response = await call_next(request)
        response.headers["Link"] = (
            f'<{SITE}/LICENSE>; rel="license"; title="Elastic License 2.0 (code)", '
            f'<{SITE}/TERMS.md>; rel="terms-of-service"; title="corpus terms"'
        )
        return response

    _mount_discovery_surface(app)

    @app.exception_handler(EightyKError)
    async def domain_error(request: Request, exc: EightyKError) -> JSONResponse:
        code = next((status for kind, status in STATUS_FOR.items() if isinstance(exc, kind)), 500)
        if code >= 500:
            log.error("unhandled_domain_error", error=str(exc), kind=type(exc).__name__)
        elif code == 429:
            # TERMS.md section 4 forbids bulk extraction. A limit that refuses
            # silently makes the clause unenforceable in practice, because
            # nobody can show a pattern after the fact -- so a breach is a
            # logged event, not just a status code.
            log.warning("rate_limited", ip=client_ip(request), detail=str(exc))
        return JSONResponse(
            status_code=code, content={"error": type(exc).__name__, "detail": str(exc)}
        )

    return app


app = create_app()
