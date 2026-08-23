# AGENTS.md — operating manual for 80085.ai

Read this before changing anything. It is written for a coding agent, so it
states the rules that are not obvious from the code.

## What this is

**80085 is a shared, evidence-backed memory of executable solutions that AI
agents can discover, run, verify, and improve.**

It is not a coding agent, not a chat app, and not primarily a container
registry. The thesis it exists to prove:

> If an agent can discover a proven executable solution faster and more
> reliably than it can recreate it, the agent will reuse it.

Six operations matter: **DISCOVER, RECALL, EXECUTE, VERIFY, RECORD, REUSE.**

The single test that proves the product is
`tests/e2e/test_cross_agent_reuse.py`. If it fails, nothing else here matters.

## Naming

The brand is **80085**. Python import names cannot start with a digit, so the
import namespace is `boobs_*` — the word 80085 spells on a calculator, which
is the joke the brand is built on. Distribution names, images, queues, service
names and docs all read `80085`.

| Layer | Name |
|---|---|
| Distributions | `80085-api`, `80085-domain`, … |
| Imports | `boobs_api`, `boobs_domain`, … |
| Env vars | `BOOBS_API_KEY`, `BOOBS_BOOTSTRAP_TOKEN`, … |
| Queue | the `executions` table (Postgres) |
| Registry repos | `<registry>/80085/<capability>` |
| Containers | `80085-<execution_id>` |

## Architecture

```
AI AGENTS ──► MCP ─┐
                   ├─► API ──┬─► RETRIEVAL ──► EXPERIENCE REGISTRY
AI AGENTS ──► HTTP ┘    ▲    ├─► EVENT STORE
                        │    └─► QUEUE (Postgres, SKIP LOCKED)
                        │              ▲
                   lease│result        │ lease
                        └──────── WORKER ──► SANDBOX ──► ARTIFACT
                                 (off-platform, Docker)
                        VERIFICATION runs in the API, never in the worker
                                  └──► EVIDENCE
```

**The API never executes an artifact and never touches the Docker daemon.**
That is not a style preference; it is the boundary the whole security model
rests on.

| Path | Role |
|---|---|
| `apps/api` | FastAPI. `/v1` endpoints, auth, ranking, enqueue. |
| `apps/worker` | HTTPS client. Lease → sandbox → report. Holds only `worker:execute`. |
| `apps/mcp` | MCP server. Five tools; an HTTP client of the API, not a backdoor. |
| `apps/web` | Static discovery surface (landing, `llms.txt`, integration docs). |
| `packages/domain` | Entities and protocols. **Imports no infrastructure, ever.** |
| `packages/schemas` | Pydantic wire models + SQLAlchemy tables. |
| `packages/retrieval` | Intent normalization, hard filters, hybrid retrieval, ranking. |
| `packages/execution` | `ExecutionRuntime` protocol, `DockerOciRuntime`, `E2BRuntime`, result cache. |
| `packages/verification` | `Verifier` protocol + verifier registry. |
| `packages/reputation` | Evidence recomputed from immutable rows. |
| `packages/security` | API keys, scopes, `PolicyEngine`, tenant visibility. |
| `packages/observability` | OTel tracing, structlog JSON logs, product metrics. |
| `packages/common` | ids, clock, config, errors, object storage. |

Infrastructure implements the protocols in `packages/domain/protocols.py`.
Never the reverse. That is what lets Docker become Firecracker/gVisor/WASI
without the product domain changing.

## Local development

Prerequisites: Docker Desktop running, `uv`, Python 3.12+.

```bash
docker compose up -d          # postgres(+pgvector), minio, registry
uv sync --all-packages
uv run alembic upgrade head
uv run python scripts/build_capabilities.py   # build example artifacts, capture digests
make api                      # terminal 1
uv run python scripts/create_worker_key.py    # mint a worker key
BOOBS_API_KEY=sk_80085_... make worker        # terminal 2 — needs Docker
uv run python scripts/seed.py # two orgs + the example Experiences
```

Postgres is published on host port **55432**, not 5432: a native PostgreSQL
service commonly owns 5432 and silently wins the bind.

The worker is deliberately absent from `docker-compose.yml`. It needs the
Docker daemon, and handing a container the host socket would undo the very
isolation the sandbox provides. It talks to the API over HTTPS and holds only
a `worker:execute` key — no database credentials, ever.

## Tests

```bash
make test              # unit + integration
uv run pytest tests/unit          # pure, no services
uv run pytest tests/integration   # real Postgres: triggers, tenancy, filters
uv run pytest tests/security      # real containers: escape and exhaustion
uv run pytest tests/e2e           # THE test: cross-agent reuse
make benchmark                    # control vs treatment
```

Service-backed tests **skip loudly** rather than mock. A mocked sandbox proves
nothing about isolation and a mocked database proves nothing about tenancy.

## Security rules

Treat every artifact as hostile.

* Artifacts are executed **by digest only**. A tag is refused at the API
  boundary and again in the runtime. If bytes could change under a version,
  every success rate in the system would be a lie.
* The sandbox gets: `--network none`, `--read-only`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, `--user 65534`, cpu/memory/pids/time
  limits, no host mounts, no Docker socket, no ambient credentials.
* An Experience that asks for the network gets a filtered bridge, never the
  default one: link-local, cloud metadata, loopback and RFC1918 are dropped
  whatever the flag says, and a run is refused if those rules cannot be
  installed. See `docs/security.md` and DECISIONS 25.
* How long a run may take is a tier (`quick`/`standard`/`extended`) granted
  through the `policies` table, not a number a recorder chooses. DECISIONS 26.
* Inputs and outputs move as tar streams via `docker cp`. That is why no bind
  mount is needed — do not add one.
* Never put secrets in source, Experience metadata, embeddings, execution
  logs, manifests, or Git.
* **Never weaken a test in `tests/security/` to make it pass.** Fix the sandbox.

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres DSN (`postgresql+asyncpg://…`). |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Execution outputs and logs. |
| `ARTIFACT_REGISTRY` | Registry that `scripts/build_capabilities.py` pushes to. |
| `SANDBOX_*` | Policy defaults: cpu, memory_mb, tmpfs_mb, timeout_seconds, pids, max_output_bytes. |
| `BOOBS_BOOTSTRAP_TOKEN` | Guards `/v1/bootstrap`, which mints API keys. |
| `BOOBS_EMBEDDER` | `auto` (default), `fastembed`, or `hashing`. |
| `BOOBS_RUNTIME` | `docker` (default) or `e2b`. Picks the worker's sandbox. |
| `E2B_API_KEY` | Required by `BOOBS_RUNTIME=e2b`. Never defaulted, never in a file. |
| `BOOBS_EXEC_CACHE` | `0` (default) or `1`. Replays identical runs — read `packages/execution/cache.py` first. |
| `BOOBS_API_KEY`, `BOOBS_API_URL` | Used by the MCP server to call the API. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional; unset installs no tracer or meter at all. |

## MCP tools

| Tool | Use |
|---|---|
| `recall_experience` | Ask whether a verified solution exists. Call before solving anything non-trivial. |
| `run_experience` | Execute one exact version in the sandbox; returns output plus an independent verdict. |
| `record_experience` | Contribute a solution you proved works. `lineage` connects a fork to what it forked. |
| `get_execution` | Poll a run that had not finished when `run_experience` stopped waiting. |
| `get_experience` | Re-read a known id's status and evidence without a recall. |

## How to add an Experience

1. Write the capability under `capabilities/examples/<name>/` with a
   `Dockerfile` that satisfies the artifact contract below.
2. Describe it in `capabilities/manifest.json` and add an input plus its
   expected output under `capabilities/fixtures/<name>/`.
   `tests/unit/test_capabilities.py` then runs it without Docker and fails if
   the bytes move or the declared verifier does not accept them.
3. `uv run python scripts/build_capabilities.py` — builds, pushes, and records
   the **digest**.
4. `uv run python scripts/seed.py`, or `POST /v1/experiences` (or the
   `record_experience` MCP tool) with the digest-pinned reference, the command,
   and a `verification` block.

**Declare `json_schema` or `sha256`, never bare `exit_code`.** An exit-code
verifier is satisfied by any container that returns 0, so a capability that
does nothing earns the same evidence as one that works. Every capability in the
manifest writes `result.json` describing what it produced — including the digest
of its own output — and the verifier reads that.

**Output must be deterministic.** Evidence is only worth something if the same
input produces the same bytes: sort keys, pin separators and line terminators,
and never emit a timestamp, a locale-dependent format or a filesystem listing
order. A `sha256` verifier over non-deterministic output produces flapping
evidence, which is worse than no evidence at all.

**Artifact contract.** The image must:

* create `/work` and `chown 65534:65534 /work` (the anonymous work volume
  inherits those permissions, and the process runs as uid 65534);
* read inputs from and write outputs to `/work`;
* expect no network, no root, and a read-only root filesystem;
* exit non-zero on failure — the floor verifier believes the exit code.

## The worker protocol

```
POST /v1/worker/lease                    -> {"job": {...}} or {"job": null}
POST /v1/worker/executions/{id}/result   -> records the run, then verifies it
```

A worker leases the oldest queued execution (`SELECT ... FOR UPDATE SKIP
LOCKED`), runs it, and reports the raw result. **Verification happens in the
API**, not in the worker: a worker reports what it saw, and the platform
decides whether that counts. A worker cannot manufacture evidence.

A claim that is never reported expires (`lease_expires_at`) and the row goes
back to `queued`; after `MAX_ATTEMPTS` it is failed with a reason rather than
retried forever.

## How to add an artifact runtime

Implement `ExecutionRuntime.execute(SandboxRequest) -> SandboxResult` from
`packages/domain/protocols.py` and construct it in `apps/worker/main.py`.
Everything above it only knows the protocol. Every limit in spec §15 must be
enforced by the new runtime, and `tests/security/` must pass unchanged.

## How to add a verifier

Write one async function `(SandboxResult, config) -> VerificationResult` in
`packages/verification/verifiers.py` and add one line to `REGISTRY`. Verifiers
must be deterministic and recomputable from stored execution artefacts. An
LLM judgment may assist later but must never be the sole source of truth.

## How to change the schema

1. Edit `packages/schemas/tables.py`.
2. `uv run alembic revision -m "…"` and hand-write anything the ORM cannot
   express (triggers, extensions, index types).
3. Add a test. Schema changes without tests are refused.
4. Destructive migrations require explicit review.

`experience_versions`, `execution_events` and `verifications` are append-only
and `executions` cannot be updated once terminal — enforced by triggers, not
by convention. If you need to "fix" a row, you need a new row.

## Operating rules for autonomous work

**Always**: inspect before modifying; use MCP tools instead of guessing
infrastructure; make small changes; run tests after meaningful changes; lint
and type-check; record decisions in `DECISIONS.md`; preserve tenant isolation;
treat artifacts as hostile; record uncertainty.

**Never**: invent credentials or infrastructure; expose secrets; disable
security to make tests pass; claim a deployment succeeded without checking it;
claim tests passed without running them; add dependencies without need; build
speculative infrastructure before proving value.

Deliberate shortcuts are marked with a `ponytail:` comment naming the ceiling
and the upgrade path. Grep for them before assuming something is an oversight.
