# Image for the API and the MCP server.
#
# Not for the worker: the worker needs a container runtime, and giving a
# container the host's Docker socket would defeat the sandbox it exists to
# operate. The worker runs on a host that has Docker (see AGENTS.md).

# The site is build output, not source: apps/web/public is generated from
# apps/web/content.js and is not committed. Building it here is what lets the
# API host serve the landing page and the agent-readable representations of it.
# Node stdlib only — build.mjs has no dependencies, so there is nothing to
# install and no lockfile to honour.
FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/ ./
# The licence and terms live at the repository root but have to be served from
# the site's document root, or every descriptor pointing at /TERMS.md 404s.
COPY LICENSE TERMS.md CONTRIBUTING.md ./legal/
RUN node build.mjs


FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependency layer first so source edits do not reinstall the world.
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/ apps/
RUN uv sync --frozen --all-packages --no-dev

COPY migrations/ migrations/
COPY alembic.ini ./
COPY --from=web /web/public/ apps/web/public/

RUN useradd --uid 10001 --create-home app && chown -R app:app /app
USER app

EXPOSE 8000

# Shell form on purpose: hosting platforms inject the port as $PORT, and an
# exec-form CMD would pass the literal string "$PORT" to uvicorn.
CMD ["sh", "-c", "uvicorn boobs_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
