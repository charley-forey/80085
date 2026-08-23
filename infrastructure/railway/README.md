# Railway deployment

What runs where, and why.

| Service | Where | Why |
|---|---|---|
| `api` | Railway | Stateless HTTP. Scales horizontally. Never touches Docker. |
| `mcp` | Railway | Thin HTTP client of the API. |
| `postgres` | Railway (pgvector) | System of record. |
| `redis` | Railway | Execution queue. |
| object storage | Railway MinIO **or** Cloudflare R2 | Execution outputs and logs. Railway has no native S3. |
| `worker` | **A host with Docker** | Needs a container runtime; see below. |

## Why the worker is not on Railway

Railway standard services cannot run Docker-in-Docker, and giving a container
the host's Docker socket would undo the isolation the sandbox exists to
provide. The specification's own infrastructure line is
"Railway + Vercel + **local computer** + MCP".

Run the worker wherever Docker is, pointed at the Railway services:

```bash
DATABASE_URL='postgresql+asyncpg://...railway...' \
REDIS_URL='redis://...railway...' \
S3_ENDPOINT_URL=... S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... \
uv run python -m arq boobs_worker.main.WorkerSettings
```

To move execution into the cloud later, implement `ExecutionRuntime` against
Fly Machines, E2B, Modal, or hardened Kubernetes sandboxing. Nothing above the
protocol changes.

## Deploy

The API image builds from `infrastructure/docker/Dockerfile`.

Required variables on the `api` service:

```
DATABASE_URL           postgresql+asyncpg://...      (note the +asyncpg driver)
REDIS_URL              redis://...
S3_ENDPOINT_URL        https://...
S3_BUCKET              80085
S3_ACCESS_KEY_ID       (secret)
S3_SECRET_ACCESS_KEY   (secret)
BOOBS_BOOTSTRAP_TOKEN  (secret — this endpoint mints API keys)
LOG_LEVEL              INFO
```

Migrations run as a release step: `uv run alembic upgrade head`.

Postgres needs the pgvector extension; the initial migration issues
`CREATE EXTENSION IF NOT EXISTS vector`, which requires a pgvector-capable
image.

## Before you call it deployed

Work the section 53 checklist, then run the real thing:

```bash
uv run python scripts/smoke.py --url https://<api-domain> --token "$BOOBS_BOOTSTRAP_TOKEN"
```

`scripts/smoke.py` records an Experience, executes it, checks that a verifier
proved it, confirms a second organization can recall it by paraphrase, and
confirms that organization *cannot* read the first one's execution.

A deployment command exiting 0 is not evidence. This is.
