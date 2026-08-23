# Architecture

```
                          AI AGENTS
                              │
                    ┌─────────┴─────────┐
                   MCP                 HTTP
                    └─────────┬─────────┘
                              ▼
                             API                 ← never executes artifacts
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
           RECALL          RECORD          EXECUTE
              │               │               │
              ▼               ▼               ▼
          RETRIEVAL      EVENT STORE        QUEUE
              │               │               │
              ▼               │               ▼
          EXPERIENCE          │            WORKER          ← the only process
           REGISTRY           │               │              that talks to a
                              │               ▼              container runtime
                              │            SANDBOX
                              │               │
                              │               ▼
                              │            ARTIFACT (by digest)
                              │               │
                              └──────────► VERIFICATION
                                              │
                                              ▼
                                           EVIDENCE
```

## The one rule

**The API never executes an artifact and never touches the container daemon.**

Everything else in this document is a consequence of that. The API can be
scaled, restarted, and exposed publicly because it only ever reads, ranks,
records and enqueues. The worker holds the dangerous capability, and it holds
it in exactly one file: `packages/execution/docker_oci.py`.

## Request paths

### RECALL

```
POST /v1/experiences/recall
  → authenticate (API key hash → Principal)
  → PolicyEngine.authorize("experience.recall")
  → intent normalization        packages/retrieval/intent.py
  → hard compatibility filters  SQL: visibility, tenant, os, arch, runtime,
                                     network policy, required capabilities
  → lexical retrieval           ts_rank_cd over a GIN-indexed tsvector
  → vector retrieval            pgvector cosine over an HNSW index
  → candidate merge             reciprocal rank fusion (selection only)
  → ranking                     relevance × (floor + quality)
  → top N with evidence
```

Filters remove what *cannot* work. Ranking orders what *might*. Confusing the
two is how a registry starts recommending things that fail.

### EXECUTE

```
POST /v1/experiences/{id}/execute
  → authorize against the Experience's visibility (public crosses tenants)
  → resolve the exact version and its artifact digest
  → INSERT execution (queued), COMMIT      ← before enqueue, so the worker
  → stage inputs to object storage            can see the row it is sent
  → enqueue on 80085:executions
  → (optional) block until terminal

worker
  → load execution, version, artifact       ← missing row ⇒ "abandoned",
  → mark running, append execution.started     never retried forever
  → sandbox: pull by digest, create, cp in, start, wait, cp out, rm -v
  → append execution.completed
  → run the declared verifier
  → append verification.completed
  → recompute evidence from immutable rows
```

## Data model

```
Organization ─┬─ Agent ─── ApiKey
              └─ Experience ─── ExperienceVersion ─── Artifact (digest)
                                       │
                       Execution ──────┤
                          ├─ ExecutionEvent   (append-only)
                          └─ Verification     (append-only)
```

`experience_versions`, `execution_events` and `verifications` reject UPDATE and
DELETE. `executions` reject DELETE, and reject UPDATE once terminal. Enforced
by triggers in `migrations/versions/0001_initial.py`.

`execution_stats` is a **cache** of evidence derived from those rows, not a
source of truth.

## Where the seams are

| Seam | Protocol | Current implementation | Swap to |
|---|---|---|---|
| Execution | `ExecutionRuntime` | Docker OCI, or E2B Firecracker (`BOOBS_RUNTIME`) | gVisor, Kata, WASI, Fly, Modal |
| Verification | `Verifier` | name→function registry | file, http, test-suite verifiers |
| Embeddings | `Embedder` | local fastembed ONNX | any hosted embedding API |
| Storage | module functions | S3/MinIO | any S3-compatible service |
| Policy | `PolicyEngine` | scopes + visibility | per-resource rules, cost caps, egress policy |

`packages/domain` imports none of them. That is what makes the table above a
table of one-file changes rather than a table of rewrites.
