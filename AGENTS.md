# AGENTS.md — operating manual for 80085.ai

Read this before changing anything. It is written for a coding agent, so it
states the rules that are not obvious from the code.

## What this is

**80085 stops an agent guessing about what it cannot know, and gets each of
those questions answered once.** The loop is **detect → halt → (optionally)
recall**: the agent notices that the answer turns on a convention absent from
the input, names exactly what is missing, and refuses — and only then, if a
record of that question already exists, does an answer come back.
Read [`docs/the-loop.md`](docs/the-loop.md) before changing anything that
touches this.

It is not a coding agent, not a chat app, and not primarily a container
registry. It is also not a memory. Storage and recall were never the
bottleneck.

**Two earlier theses were measured and abandoned. Do not reintroduce either.**

The founding one was that an agent reuses a proven solution when discovering it
is faster and more reliable than recreating it. Both halves are false.
Treatment cost **3.6x to 5.8x more input tokens** than an agent with a `bash`
tool and no registry, and nothing about time is measurable at achievable sample
sizes — the same arm on the same task took 34.4s, 65.6s and 88.7s
(DECISIONS 71). On the correctness cases an unaided agent scored **11 of 12**:
it does not need us to be right about a delimiter it can read for itself
(DECISIONS 72).

The one that replaced it was deference — knowledge an agent cannot derive
winning an argument against the agent's own confidence. It works when the
answer is true and fails when it is not. **Control scored 0 of 9** on the three
valid non-derivable capabilities: never right, never an error, always a
plausible silent wrong answer. Treatment with every part of the system working
scored **2 of 9** — the agent received the verified answer, adjudicated it
against its own reading, and preferred itself. One paragraph instructing it to
defer took treatment from **2/9 to 9/9** (DECISIONS 73-74). But the same
disposition swallows a wrong Experience **3/3** (DECISIONS 75), and still
swallows it **2/3** after naming its own gap (DECISIONS 79). Corroboration is
the only working gate, and a single tenant has one party, so `use` is
unreachable and the gate is unavailable exactly where the knowledge lives.

**Detection, meanwhile, is 9/9 on `claude-opus-5`, `claude-sonnet-5` and
`claude-haiku-4-5`** (DECISIONS 76-77). So the system is built on the half that
is reliable, and the safety-critical step is the one that **asserts nothing**.

Measured on the halt (DECISIONS 80-81):

* Silent wrong answers **0 of 9**, against **9 of 9** unaided, with every one
  converted into a named, answerable question. Derivable tasks still solved
  9 of 12.
* **0 wrong answers out of 15** under pressure — *"just the number"*, *"a best
  guess is genuinely fine"*, *"last time an assistant refused and it was
  useless"* — and the halts stayed **specific**, naming the same missing field
  every time rather than degrading into vagueness. In a three-step pipeline
  with only the middle step unknowable, the agent refused rather than filling
  the gap to complete the report shape.
* On six conventions drawn from how industries actually work rather than
  invented by us: silent wrong answers **6 of 18 unaided, 0 of 18 with the
  halt**.

Two of those six were badly designed, and it is the most useful thing they
produced: `2/10 net 30` and FTE proration are standard practice, absent from
the file but firmly in training, so the agent got them right unaided —
correctly. That sharpened the target class:

> The market is not knowledge the agent lacks. It is **a choice between
> conventions the agent has no basis to make.**

The agent knows both readings of an end date; it cannot know which one *this*
organisation uses, and picks one silently and wrongly 3/3. The answer is a fact
about one organisation's decisions rather than about the world, so it **cannot**
live in a public corpus. Private, self-hosted deployment is not a go-to-market
preference; it is where this class of knowledge exists at all. The public corpus
is proof and on-ramp, not the product.

**Open risk, do not paper over it.** Trust transfer is not fixed, only avoided.
The moment a recorded answer comes back, DECISIONS 74, 75 and 79 return in
full — the agent may overrule it, or swallow it when wrong. A halt is safe
because it asserts nothing; a recall is not, and nothing in the codebase
currently makes it safe. Inside one organisation the intended answer is
attestation — a named human accountable for what was recorded — which is
designed, unbuilt and unmeasured. Also unmeasured: whether any of this holds on
a *real* organisation's real convention. Every fixture above is data we
constructed.

Six operations matter: **DISCOVER, RECALL, EXECUTE, VERIFY, RECORD, REUSE** —
and the step upstream of all six, which is the one safety rests on: **HALT**.

`tests/e2e/test_cross_agent_reuse.py` proves the loop closes, and it is
necessary but no longer sufficient: it passed for every one of the 2/9 runs.
What proves the product is `benchmarks/agent_halt.py` and
`benchmarks/real_conventions.py` — zero silent wrong answers — plus
`benchmarks/agent_halt_pressure.py`, which fails first if a halt stops
surviving a user who wants a number now.

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
| `packages/reputation` | Evidence, always rederivable from immutable rows. |
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
uv run pytest tests/e2e           # the reuse loop, end to end
make benchmark                    # control vs treatment; see benchmarks/
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
| `EVIDENCE_MIN_PROMOTION_ORGANIZATIONS` | Distinct organizations required before an Experience is VERIFIED or recommended as `use`. Default 2. |
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
| `recall_experience` | Ask whether the question you just halted on has already been answered. Call it *after* you have detected the gap and named what is missing — not on everything; on `csv_to_json` the same call is pure overhead. A miss is not a licence to guess: halt. |
| `run_experience` | Execute one exact version in the sandbox; returns output plus an independent verdict. When verification passed *and* the result supplies the convention you named, those values are the answer — not a second opinion to weigh against your own reading. Deference is not unconditional: a result that does not answer the question you halted on is not an answer, and adopting it anyway is the measured failure in DECISIONS 79 (wrong result adopted 2/3 even after the gap was named). Halt instead. |
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

**A new capability needs a documented case where the obvious implementation
returns a plausible wrong answer**, and the rule that produces it must not
appear anywhere in the fixture. If an agent can read the rule out of the input
it is testing nothing: control scored 3/3 on `part_supersede_orbital` for
exactly that reason and the capability was thrown out. DECISIONS 71, 74.

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
