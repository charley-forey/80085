# Scaling: what actually breaks first

Written when recall was opened to callers with no key, because that is the
change that makes traffic real. The honest summary: **the read path is already
in good shape, and the write path is the constraint** — which is the right way
round, because reads are what we want unlimited and writes are what cost money.

Numbers here are measured against the code, not guessed. Where something is a
known ceiling rather than a limit, it says so.

## What is already fine

**Retrieval is properly indexed.** The expensive part of recall is finding
candidates, and the indexes for it exist:

| Index | Column | Why it matters |
|---|---|---|
| `ix_versions_embedding` | `embedding`, **HNSW** `vector_cosine_ops` | Vector search stays sub-linear as the corpus grows. Without it, every recall is a sequential scan over every version. |
| `ix_versions_tsv` | `tsv`, GIN | Full-text half of the hybrid retrieval. |
| `ix_versions_filters` | `os, architecture, runtime, requires_network` | The hard compatibility filters run before ranking. |
| `ix_executions_queue` | `status, created_at` | Lease claims do not scan the execution table. |

**The static site does not scale — it is already served from a CDN.** The only
dynamic thing on the page is one keyless recall query.

**Ranking cost is bounded.** Wilson and RRF run over the candidate set, not the
corpus.

## What breaks first, in order

### 1. Embedding on the request path

Every recall embeds the query text with a local model (`fastembed`,
BAAI/bge-small-en-v1.5). That is CPU work inside the request, and it is the
single hottest thing in the read path.

The fix when it hurts, cheapest first:

1. **Cache by normalized query text.** Popular questions repeat, and the same
   words produce the same vector. A small LRU in the API process costs nothing
   and removes the duplicate work.
2. Move embedding to its own service so the API stays IO-bound.
3. Only then, a hosted embedding API — which reintroduces a network hop and a
   vendor on the read path, so it is genuinely the last resort.

### 2. Rate limits — done, and no longer a reason not to scale out

`apps/api/src/boobs_api/limits.py` used to keep counters in process, so with N
replicas the effective limit was N times the configured one and every deploy
reset it. The window is now a row in `rate_limits`: one counter per caller per
limit per time bucket, incremented with a single
`INSERT ... ON CONFLICT DO UPDATE ... RETURNING hits`.

Cost on the hot path is one round trip and one primary key lookup, on the
request's own session — no second pooled connection, so this does not eat into
the budget in section 3. Expired rows are deleted on every thousandth check.

Two ceilings remain, both marked in the file: the windows are fixed rather
than sliding (up to 2x the limit across a boundary), and `client_ip` trusts
exactly one proxy hop. A CDN in front of Railway would collapse callers into
the CDN's edge addresses; take the Nth `X-Forwarded-For` entry from the right
at that point.

Redis stayed gone. It was removed when the queue moved to leases, and one
counter does not justify bringing it back.

### 3. Connection pool

`pool_size=10, max_overflow=10` per process. Postgres has to accommodate
`replicas × 20` plus the worker. Raise Postgres `max_connections` or put
PgBouncer in front *before* scaling the API horizontally, not after — running
out of connections looks like a slow site, not like a connection error.

### 4. Execution is the genuine constraint

Everything above is cheap. Running an artifact is not: it needs a machine with
a container runtime, and the worker cannot live in the API image because giving
a container the host's Docker socket would defeat the sandbox it exists to
operate.

Executions are leased from Postgres (`apps/api/src/boobs_api/leases.py`), so
adding capacity is adding worker hosts — no queue to shard, no coordination.
`/v1/ready` reports `queued_executions`; a backlog that does not drain is the
signal to add one.

This is also why `run` has the tightest rate limit of the four operations.

## Scaling the number of people, not the number of requests

Traffic is the easy half. The reason to care about any of the above is that a
shared brain is worth what has been recorded in it, so the number that matters
is contributors, not requests per second.

That is why recall needs no key, why keys mint without a signup, and why
recording defaults to public. Each of those removes a reason for someone to
close the tab. The rate limits exist so that openness has a floor, not so that
it has a ceiling.

## What we deliberately have not built

YAGNI, until something measured says otherwise:

- read replicas — one Postgres is a long way from saturated
- sharding, multi-region, Kubernetes
- a CDN in front of the API — the responses are per-caller and per-query
- autoscaling policies — with one replica there is nothing to scale between

The first three would all add failure modes we would then have to debug, in
exchange for headroom nothing is currently asking for.

## What to watch

- `/v1/ready` → `queued_executions` climbing and not draining → add a worker
- recall latency → embedding cache is the first lever
- 429s in the logs → either genuine abuse, or the limits are too tight for a
  legitimate user, and the message tells them they can self-host
- Postgres connection count approaching `max_connections`
