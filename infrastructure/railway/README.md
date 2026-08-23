# Deployment

## Live

| Surface | URL |
|---|---|
| API + discovery surface | https://api-production-0734.up.railway.app |
| Landing page | `/` |
| Machine-readable brief | `/llms.txt` |
| OpenAPI | `/openapi.json` · `/docs` |
| Artifact registry | `registry-production-ca7f.up.railway.app` |

## Topology

| Service | Where | Why |
|---|---|---|
| `api` | Railway | Stateless HTTP. Serves `/v1`, the landing page and `llms.txt`. Never touches a container runtime. |
| `mcp` | Railway | Hosted MCP endpoint (streamable-http). Holds no key; forwards each caller's own. |
| `Postgres` | Railway | System of record **and** the execution queue (`SELECT ... FOR UPDATE SKIP LOCKED`). |
| `minio` | Railway + volume | Execution outputs and logs. |
| `registry` | Railway + volume | The project's own OCI artifact registry, digest-addressed and authenticated. |
| `worker` | **Any host with Docker** | Runs sandboxes. Talks HTTPS to the API and holds only a `worker:execute` key. |

There is no Redis: the queue lives in Postgres (see `DECISIONS.md` 8 and 17).

## Why the worker is not on Railway

A managed platform will not give a service a container runtime, and handing a
container the host's Docker socket would undo the isolation the sandbox exists
to provide.

So the worker runs wherever Docker is and reaches the platform over HTTPS
only. It never receives database or object-storage credentials, and no
datastore is exposed to the internet.

```bash
uv run python scripts/create_worker_key.py \
  --url https://api-production-0734.up.railway.app --token "$BOOBS_BOOTSTRAP_TOKEN"

docker login registry-production-ca7f.up.railway.app -u 80085     # to pull artifacts

BOOBS_API_URL=https://api-production-0734.up.railway.app \
BOOBS_API_KEY=sk_80085_... \
uv run 80085-worker
```

With no worker attached the API still records and recalls; executions simply
queue. `/v1/ready` reports `queued_executions` so that is visible rather than
merely slow.

To move execution into the cloud, implement `ExecutionRuntime` against Fly
Machines, E2B, Modal, or hardened Kubernetes sandboxing. Nothing above the
protocol changes.

## Service configuration

The API builds from `infrastructure/docker/Dockerfile`; the registry from
`infrastructure/registry/Dockerfile` with root directory
`infrastructure/registry`.

Variables on `api`:

```
DATABASE_URL           ${{Postgres.DATABASE_URL}}   (the plain postgresql:// URL is fine)
S3_ENDPOINT_URL        http://minio.railway.internal:9000
S3_BUCKET              80085
S3_ACCESS_KEY_ID       (matches MINIO_ROOT_USER)
S3_SECRET_ACCESS_KEY   (matches MINIO_ROOT_PASSWORD)
BOOBS_BOOTSTRAP_TOKEN  (secret — this endpoint mints API keys)
BOOBS_EMBEDDER         fastembed
```

Migrations run as a pre-deploy step: `alembic upgrade head`.

**The Postgres image must ship pgvector.** Use
`ghcr.io/railwayapp-templates/postgres-ssl:18`; plain `postgres:*` does not
include it. Swapping to an image without pgvector leaves the extension
registered in the catalog but its shared library missing, so `SELECT 1` still
answers while every recall returns 500. `/v1/ready` now reports `pgvector`
separately for exactly this reason — check it after any database change.

## Publishing an artifact

```bash
docker login registry-production-ca7f.up.railway.app -u 80085
ARTIFACT_REGISTRY=registry-production-ca7f.up.railway.app \
  uv run python scripts/build_capabilities.py
```

The script records the **digest** the registry assigned. That digest, never a
tag, is what an Experience stores.

## Before you call it deployed

```bash
uv run python scripts/smoke.py \
  --url https://api-production-0734.up.railway.app --token "$BOOBS_BOOTSTRAP_TOKEN"
```

It records an Experience, executes it, checks a verifier proved it, confirms a
second organization recalls it by paraphrase, and confirms that organization
*cannot* read the first one's execution.

A deployment command exiting 0 is not evidence. This is.
