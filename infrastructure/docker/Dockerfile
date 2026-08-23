# Image for the API and the MCP server.
#
# Not for the worker: the worker needs a container runtime, and giving a
# container the host's Docker socket would defeat the sandbox it exists to
# operate. The worker runs on a host that has Docker (see AGENTS.md).
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

RUN useradd --uid 10001 --create-home app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "boobs_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
