# Decisions

Choices the specification left open, what they cost, and how to undo them.
Recorded because the next agent needs to know what was decided deliberately
and what was merely convenient.

---

### 1. Import namespace is `boobs_*`, everything else is `80085`

Python identifiers cannot start with a digit, so `import 80085_domain` is a
syntax error. The import namespace uses the word 80085 spells on a calculator,
which is the brand. Distribution names (`80085-api`), images, queues, service
names, env vars and docs all read 80085.

**Undo:** a mechanical rename; nothing depends on the spelling.

---

### 2. uv workspace, one lockfile

`[tool.uv.workspace]` over per-package virtualenvs or a src-less flat layout.
One resolve, one lockfile, one `uv sync --all-packages`.

---

### 3. Postgres on host port 55432

A native PostgreSQL service commonly owns 5432 on developer machines and wins
the bind silently, producing an authentication error that looks like a
password bug. The container is published on 55432 instead of asking anyone to
stop their local service.

---

### 4. Embeddings: local `fastembed` (BAAI/bge-small-en-v1.5, 384-dim)

No API key, no network at query time, deterministic in CI. Behind an
`Embedder` protocol.

`BOOBS_EMBEDDER=auto|fastembed|hashing`. `auto` falls back to a non-semantic
hashing embedder if the model cannot load, and **logs a warning** — silent
degradation of recall quality would be the hardest failure to notice from
outside.

**Undo:** implement `Embedder`, change one factory.

---

### 5. Retrieval columns live on `experience_versions`, not a separate table

Spec §11 offers an optional `experience_embeddings` table. Keeping
`search_text`, `tsv` and `embedding` on the version row means hard
compatibility filters and ranking happen in one query with no join.

**Cost:** re-embedding rewrites version rows, which are append-only. In
practice a re-embed creates a new version, which is the correct semantics
anyway.

---

### 6. Relevance multiplies; it does not add

**This was a bug before it was a decision.** The first implementation
normalized RRF scores against the best candidate, so the top hit always scored
relevance 1.0 no matter how poorly it matched — and because evidence weights
summed higher than the relevance weight, a heavily-used Experience could win a
query it did not answer. The benchmark caught it: every task recalled
`csv_to_json`.

Now:

* relevance is a real similarity (cosine similarity, or squashed
  `ts_rank_cd`), not a rank position;
* RRF is used only to choose which candidates to consider;
* `final = relevance × (0.45 + 0.55 × quality)`, so evidence can only amplify
  a match that is already the right thing;
* an exact intent match raises **relevance**, never the evidence — matching
  the task is not the same as being known to work;
* below `MIN_SCORE` nothing is returned at all. An empty answer is a correct
  answer; a confident wrong capability is worse than no registry.

Locked in by `tests/integration/test_recall_picks_the_right_capability.py`.

A second retrieval defect surfaced the same way. "export json records as a
spreadsheet-friendly csv" mentions three formats but names two — the CSV is
what is produced and "spreadsheet" merely describes it. Intent normalization
read the target as XLSX, lost the direction of the conversion, and recalled
`csv_to_json` for a `json_to_csv` task. Format words within two words of each
other now collapse to the head noun, unless a direction word ("to", "into",
"from", "as") sits between them — because "pdf to json" is also two words
apart and does name two formats.

---

### 7. Confidence is a Wilson lower bound, not a success rate

A plain rate reports 100% after one lucky run. Wilson reports ~21%, which is
the number an agent should act on. Same few lines of code, correct at small n.
Spec §19 defers "contextual/Bayesian confidence"; this is the cheap half of it
and there was no reason to ship the wrong one first.

---

### 8. Queue is Postgres, not Redis  *(superseded decision 8: arq)*

The queue was arq on Redis until the worker moved off-platform. It is now the
`executions` table itself, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`:
exactly one worker gets each row, concurrent claimers step over locked rows
rather than blocking, and the queue cannot drift from the execution history
because they are the same rows.

Redis is gone entirely. It was carrying one thing, and Postgres was already
there.

Historical note -- the arq design said:

Async-native and Redis-backed. Celery is sync-first and heavy for three job
types.

> Async-native and Redis-backed. Celery is sync-first and heavy for three job
> types. A job naming an execution row that does not exist returns
> `"abandoned"` instead of raising.

The same failure mode is now handled by lease expiry: a claim that is never
reported expires, the row returns to `queued`, and after `MAX_ATTEMPTS` it is
failed with a reason rather than retried forever.

---

### 8b. One queue database per environment, and never launch the worker through a wrapper

Two operational bugs, found by the benchmark rather than by reasoning:

* `subprocess.terminate()` on a `uv run arq …` process kills the wrapper and
  **orphans the worker** on Windows. Orphans from earlier runs kept consuming
  from the shared queue while pointed at a database that had since been
  dropped, so roughly half of all jobs failed with `NoResultFound` and real
  executions sat at `queued` until they timed out. Workers are now launched as
  `sys.executable -m arq …` — one process, and terminating it terminates it.
* Tests, benchmarks and development each get their own Redis database
  (`/1`, `/2`, `/0`). A worker from one environment must not be able to claim
  a job whose row it cannot see.

The product-side half of this is decision 8: a job naming a missing row
returns `"abandoned"` instead of retrying.

---

### 9. Sandbox I/O by `docker cp`, work directory on an anonymous volume

Spec §15 requires no host mounts. `docker create` → `docker cp` in → `start` →
`docker cp` out satisfies that literally, with no bind mount anywhere.

`/work` is an anonymous volume rather than a tmpfs because `docker cp` into a
stopped container writes into the image layer, which a tmpfs mount would then
shadow at start.

**`ponytail:` ceiling** — tmpfs size limits therefore do not bound `/work`.
`/tmp` is still a sized tmpfs, and cpu/memory/pids/time/output are all
bounded. Upgrade path if disk abuse matters: a quota-enabled volume driver, or
`--storage-opt size=` on a driver that supports it.

---

### 10. The worker runs on a host with Docker, not on Railway

Railway standard services cannot run Docker-in-Docker, and giving a container
the host socket would undo the isolation the sandbox exists to provide. The
spec's own infrastructure line is "Railway + Vercel + **local computer** +
MCP".

API, Postgres and object storage are hosted; the worker runs where Docker is,
and reaches the platform over HTTPS only (decision 17).

**Undo:** implement `ExecutionRuntime` against Fly Machines, E2B, Modal, or a
hardened Kubernetes sandbox. Nothing above the protocol changes.

---

### 11. Evidence is recomputed, not incremented

Every recall-visible number is rebuilt from immutable `executions` and
`verifications` rows. Counters cannot drift, and a replayed history produces
identical numbers. `execution_stats` is a cache of that computation, not a
source of truth.

A run counts as **successful** only if the sandbox succeeded *and* a verifier
passed. An agent's claim is not evidence.

---

### 12. Immutability is enforced by triggers

`experience_versions`, `execution_events` and `verifications` reject UPDATE and
DELETE. `executions` reject DELETE and any UPDATE once terminal. Spec §4 says
historical execution records must remain immutable; a docstring saying so is
not enforcement.

---

### 13. Artifacts are OCI images pinned by digest, deduplicated globally

A tag is refused at the API boundary and again in the runtime. Identical bytes
are one artifact regardless of who registered them first, because the digest
*is* the identity.

Dev and CI push to a local `registry:2`; GHCR is the path for real artifacts.

---

### 14. Verifiers ship as three, extend as a registry

`exit_code`, `json_schema`, `sha256`. `file`, `http` and `test_suite` from
spec §18 are one function plus one registry line each. Building all six before
any of them had a caller would have been speculative.

---

### 15. Bootstrap endpoint mints the first API key

`/v1/bootstrap`, guarded by `BOOBS_BOOTSTRAP_TOKEN`. This is the MVP's account
creation and is meant to be replaced by a real signup flow. Keys are SHA-256
hashed at rest; the plaintext exists exactly once, in the creating response.

---

### 16. `apps/web` is static

Spec §14 asks for machine-friendly discovery surfaces: landing, integration
instructions, `llms.txt`, OpenAPI. None of that needs a framework, and a
static page deploys to Vercel with no build step.

**Deferred:** the browsable Experience explorer. It needs an authenticated
read API and a real design pass; it is not on the path to proving the thesis.

---

## Deferred deliberately (spec sections, not oversights)

Automatic experience extraction (§21), richer promotion (§22), failure
knowledge (§23), staleness sweeps (§24), autonomous maintenance and
improvement (§26–27), the Experience Graph (§28), composability (§29),
federation (§48), commerce (§49), SDKs (§42), automatic recall by agent
runtimes (§43).

Each has a named seam in the code — `lineage` on every version, the
`Verifier`/`ExecutionRuntime` protocols, the append-only event stream — but no
speculative implementation.

---

### 17. The worker speaks HTTPS, and never touches a datastore

**Found by trying to deploy.** With the worker off-platform, it needed to
reach Postgres and Redis. Railway's TCP proxy accepted connections at the edge
but never forwarded them to either container, so the datastores were
unreachable — and the design that required exposing them was the wrong design
anyway.

A worker is now an HTTPS client of the API:

```
POST /v1/worker/lease                      claim the oldest queued execution
POST /v1/worker/executions/{id}/result     report what happened
```

What this bought, beyond unblocking the deployment:

* **A worker holds one narrow key.** `worker:execute` and nothing else — it
  cannot recall, cannot record, cannot read another tenant's experiences. A
  leaked worker key does not expose the registry.
* **No datastore is on the internet.** Postgres and object storage stay
  private to the platform. The public surface is one API.
* **A worker cannot vote on its own evidence.** It reports the raw result —
  exit code, stdout, output bytes — and *the API* runs the verifier. Under the
  old design the worker verified its own run and wrote the verdict to the
  database, which meant a compromised or buggy worker could manufacture
  evidence. That is precisely the thing this product sells, so it does not
  belong on the untrusted side of the boundary.

Locked in by `tests/integration/test_worker_protocol.py`, including a worker
that reports success while producing output the verifier rejects.

**Undo:** none wanted. This is better than what it replaced on every axis
except one — a worker now polls rather than being pushed to, which costs a few
seconds of latency on an idle queue.

---

### 18. Readiness proves pgvector works, not that it exists

**Found in production.** A Postgres image was swapped for one without
pgvector. The extension stayed registered in the catalog, `SELECT 1` kept
answering, `/v1/ready` kept reporting `database: true` — and every recall
returned 500, because the extension's shared library was gone.

`/v1/ready` now casts a vector literal. That touches the library, so the probe
fails when recall would fail rather than after someone reports it.

The general rule this is an instance of: **a health check must exercise the
dependency the way the product does.** Checking that a connection opens tells
you almost nothing about whether queries work.

Locked in by `tests/integration/test_readiness.py`.

**Postgres image:** `ghcr.io/railwayapp-templates/postgres-ssl:18`, which ships
pgvector. Plain `postgres:*` does not. Anything replacing it must carry
pgvector or the registry loses semantic recall.
