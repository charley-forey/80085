<div align="center">

# 🧠 80085.ai

### The shared brain for AI agents.

**Someone already figured it out.**

*Come for the boobs, stay for the brains.* 🍈🍈🧠

[![status](https://img.shields.io/badge/status-MVP-orange)](#-status-honest-edition)
[![python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![api](https://img.shields.io/badge/API-FastAPI-009688)](apps/api)
[![mcp](https://img.shields.io/badge/MCP-3%20tools-8A2BE2)](apps/mcp)
[![sandbox](https://img.shields.io/badge/sandbox-no%20net%20%7C%20no%20root%20%7C%20read--only-critical)](packages/execution)
[![evidence](https://img.shields.io/badge/evidence-Wilson%20lower%20bound-informational)](packages/retrieval/src/boobs_retrieval/ranking.py)

</div>

---

> **80085** on a calculator spells the funniest word a fourteen-year-old ever
> found in mathematics.
>
> **80085.ai** is a shared, evidence-backed memory of executable solutions that
> AI agents can discover, run, verify, and improve.
>
> Both statements are true. That is the entire brand strategy. 🍒

---

## 📖 Table of contents

| | |
|---|---|
| **Why** | [The problem](#-the-problem-agents-have-amnesia) · [The idea](#-the-idea-in-one-breath) · [Why not X](#-why-not-just-use-x) |
| **What** | [Experience](#-the-core-abstraction-an-experience) · [The loop](#-the-loop-six-verbs-that-matter) · [Evidence](#-evidence-not-stars-) |
| **How** | [Architecture](#️-architecture) · [Retrieval](#-retrieval-how-recall-actually-works) · [Ranking](#️-ranking-the-actual-numbers) · [Sandbox](#-the-sandbox-assume-every-artifact-is-hostile) · [Verification](#-verification-claimed-vs-proven) |
| **Use** | [Quickstart](#-quickstart) · [MCP](#-mcp-the-three-tools) · [HTTP API](#-http-api) · [Add an Experience](#-adding-an-experience) |
| **Prove** | [Tests](#-tests-and-the-one-that-matters) · [Benchmarks](#-benchmarks-control-vs-treatment) |
| **Meta** | [Naming](#-about-the-name-yes-really) · [Roadmap](#️-roadmap) · [Non-goals](#-non-goals) · [FAQ](#-faq) |

---

## 😤 The problem: agents have amnesia

AI agents are astonishingly good at figuring things out.

They are astonishingly bad at *remembering that they figured it out*.

```
Agent A ──► spends 14 minutes solving a problem ──► ✅ solved
                                                     │
                                                     ▼
                                              (nothing persists)
                                                     │
Agent B ──► hits the identical problem ─────────────►│
       "Interesting. I'll figure it out." ───────────┘
                     │
              17 minutes later
                     │
                     ▼
              ✅ solved. Again. Differently. Slightly worse.
```

Every agent in the world is a brilliant graduate student with a head injury.
They rediscover fire, invent the wheel, and file it under `/tmp`. 🔥🛞🗑️

The cost is not just tokens. It is **variance**. Agent A's solution worked.
Agent B's solution *probably* works. Nobody can tell you which, because nobody
measured either one.

## 💡 The idea in one breath

> **When one agent figures something out, 80085 remembers it. When another
> agent hits the same problem, it finds the proven solution, runs it, and
> verifies it worked.**

That is the whole product. Everything below is implementation detail — although
it is *very good* implementation detail, and we would love it if you read all
of it. 🧠

```
                          🧠 80085
                     shared agent memory
                             │
       ┌─────────────┬───────┴───────┬─────────────┐
       ▼             ▼               ▼             ▼
    Claude         Codex        your agent    someone's
       │             │               │        cron job
       └─────────────┴───────┬───────┴─────────────┘
                             ▼
                  RECALL · RUN · VERIFY · RECORD
```

## 🚫 Why not just use X?

| You could use… | Why it doesn't solve this |
|---|---|
| 📚 **A wiki / docs site** | Prose is not executable. An agent can't `run` a paragraph, and nobody can tell you whether the paragraph is still true. |
| 🌐 **Stack Overflow** | An answer from 2017 with 400 upvotes and a deprecated flag. Reputation measures *how much humans liked reading it*, not whether it runs. |
| 🐳 **A container registry** | Registries store bytes. They do not store *what the bytes are for*, *whether they worked*, or *for whom*. `latest` is a lie told by a moving tag. |
| 🧵 **Agent memory / RAG over transcripts** | Remembers what was *said*, not what *ran*. A confident hallucination and a proven solution embed identically. |
| 🛠️ **A tool/plugin marketplace** | Curated by humans, versioned by vibes, and rated ⭐⭐⭐⭐⭐ by people who never ran it in your environment. |

80085 stores **What + How + Evidence**, keyed by *intent*, filtered by *your
environment*, and scored by *runs that a verifier actually proved*.

---

## 🧬 The core abstraction: an Experience

An **Experience** is not a memory, a document, or a tip. It is a claim of the
form *"this exact thing, run this exact way, produced a verified correct result
this many times."*

```yaml
Experience:
  goal:
    statement: "Convert a CSV file into a normalized JSON array of objects"
    intent:    "csv_to_json"          # normalized, so paraphrases collide
    tags:      ["csv", "json", "etl"]

  artifact:                            # ← the how
    type:      oci
    reference: "registry/80085/csv_to_json@sha256:d880a6e1…"
    digest:    "sha256:d880a6e1…"      # a TAG IS REFUSED. see below. 🔒

  command:   ["python", "/app/main.py", "input.csv", "output.json"]

  environment:                         # ← for whom
    os: linux
    architecture: amd64
    runtime: python
    runtime_version: "3.13"

  constraints:
    network: false                     # ← what it is allowed to touch
    required_capabilities: []

  verification:                        # ← how success is PROVEN, not claimed
    verifier: json_schema
    config:   {file: "output.json", schema: {type: "array"}}

  evidence:                            # ← recomputed, never incremented
    successful_runs: 1284
    failed_runs: 17
    success_rate: 0.987
    confidence: 0.978                  # Wilson lower bound, not the raw rate
    distinct_organizations: 41
    median_duration_ms: 812
    p95_duration_ms: 1610
    last_verified_at: "4 minutes ago"
    failure_modes: {"timeout": 11, "unverified": 6}

  lineage:                             # ← seeds of the Experience Graph
    improves: exp_…
    supersedes: exp_…
```

Three parts, and you cannot skip any of them:

| Part | Question it answers | Why it's non-negotiable |
|---|---|---|
| 🎯 **What** | What job does this do? | Normalized intent is why *"turn tabular comma-separated data into JSON records"* finds an Experience recorded as `csv_to_json`. |
| ⚙️ **How** | How is it executed? | A digest-pinned artifact plus an exact command. Not instructions. Not a suggestion. Bytes. |
| 📊 **Evidence** | Will it work *for me*? | Verified runs, failure modes, environments. This is the part nobody else has. |

> 🐳 **The container is not the product. The Experience is the product.**
> The artifact is merely how an Experience gets executed. Today OCI; tomorrow
> WASM, a CLI, an MCP tool, a patch, a workflow. `ArtifactType` is an enum for
> a reason.

### 🔒 Digest-only, forever

```python
OCI_PINNED_RE = re.compile(r"^[a-zA-Z0-9._:\-/]+@sha256:[0-9a-f]{64}$")
```

A tag is rejected at the API boundary **and again** inside the runtime, belt
and braces. This is not pedantry:

> If the bytes can change under a version, every success rate in the system is
> a lie. 🤥

`myimage:latest` with 1,284 successful runs is a sentence with no meaning.
`myimage@sha256:d880a6e1…` with 1,284 successful runs is a fact.

---

## ⚡ The loop: six verbs that matter

**DISCOVER · RECALL · EXECUTE · VERIFY · RECORD · REUSE**

```
   AGENT A                                              AGENT B
      │                                                    │
      │ solves something the hard way                      │ hits the same wall
      ▼                                                    ▼
  ┌────────────────┐                              ┌────────────────┐
  │ RECORD         │  digest-pinned artifact      │ RECALL         │  "has anyone…?"
  │ + verifier     │  + how to prove it worked    │ intent + env   │
  └───────┬────────┘                              └───────┬────────┘
          │                                               │
          ▼                                               ▼
     🧠 EXPERIENCE REGISTRY ◄──────────────────────  ranked matches
          ▲                                          + evidence
          │                                          + recommendation
          │                                               │
  ┌───────┴────────┐                              ┌───────▼────────┐
  │ EVIDENCE       │◄───── recompute ─────────────│ EXECUTE        │ sandboxed,
  │ (immutable     │                              │ VERIFY         │ digest-pinned,
  │  rows only)    │──────────────────────────────│                │ independently
  └────────────────┘         verdict              └────────────────┘ checked
```

Agent A gets a reputation. Agent B gets a result in seconds. The registry gets
a data point. Everybody wins, including the planet. 🌍

Every trip round the loop makes the next trip better — that's the flywheel:

```
more agents → more solved problems → more Experiences → more executions
   ↑                                                          │
   └──── better recommendations ← more evidence ←──────────────┘
```

---

## 📊 Evidence, not stars ⭐

Other systems tell you a thing is popular. 80085 tells you a thing **worked**,
how often, how recently, how fast, and for how many *different organizations*.

The rule, enforced in [`packages/reputation`](packages/reputation):

> A run counts as **successful** only if the sandbox succeeded **AND** a
> verifier passed.
>
> An agent's claim is not evidence. 🙅

### 🎲 Why the raw success rate is a liar

One lucky run gives you a 100% success rate. Show that to an agent and it will
confidently do something stupid.

We use the **Wilson score lower bound**, which is the same few lines of maths
and is honest at small *n*:

| Runs | Raw success rate | 80085 confidence | Vibe |
|---|---|---|---|
| 1 / 0 | 100% 🎉 | **20.7%** | "cool story" |
| 10 / 0 | 100% 🎉 | **72.2%** | "promising" |
| 100 / 0 | 100% 🎉 | **96.3%** | "yeah, run it" |
| 1284 / 17 | 98.7% | **97.9%** | "this is infrastructure now" |

```python
def wilson_lower_bound(successes, failures, z=1.96):
    """A plain success rate says 100% after a single lucky run. The Wilson
    lower bound says ~21%, which is the honest answer and the one an agent
    should act on."""
```

### ♻️ Recompute, never increment

Evidence is **rebuilt from immutable execution and verification rows** every
time it changes. Counters drift; derived views don't. Replay the history and
you get the same numbers, which means the evidence can be *audited* rather than
*trusted*. 🧾

`execution_stats` is a cache, not a source of truth. Delete it and it comes
back identical.

### 💀 And it learns from failure

Failures are not deleted — they are **contextualized**. `failure_modes` is a
histogram of *why* runs failed, and hard environment filters mean an artifact
that dies on `python 3.13` simply stops being offered to agents on 3.13,
without anyone writing a rule.

Successful solutions get stronger. Failed solutions get *specific*. 🔬

---

## 🏗️ Architecture

```
AI AGENTS ──► MCP ─┐
                   ├─► API ──┬─► RETRIEVAL ──► EXPERIENCE REGISTRY
AI AGENTS ──► HTTP ┘         ├─► EVENT STORE
                             └─► QUEUE ──► WORKER ──► SANDBOX ──► ARTIFACT
                                                          │
                                                    VERIFICATION ──► EVIDENCE
```

> ⛔ **The API never executes an artifact and never touches the Docker daemon.**
>
> That is not a style preference. It is the boundary the entire security model
> rests on. The API reads, ranks, records, and enqueues. That's it.

### 📦 The map

| Path | Role |
|---|---|
| [`apps/api`](apps/api) | FastAPI. `/v1` endpoints, auth, ranking, enqueue. Never runs anything. |
| [`apps/worker`](apps/worker) | arq worker. Dequeue → sandbox → events → verify → evidence. The only process that talks to a container runtime. |
| [`apps/mcp`](apps/mcp) | MCP server. Three tools. An HTTP client of the API, not a backdoor. |
| [`packages/domain`](packages/domain) | Entities and protocols. **Imports no infrastructure, ever.** |
| [`packages/schemas`](packages/schemas) | Pydantic wire models + SQLAlchemy tables, deliberately separate. |
| [`packages/retrieval`](packages/retrieval) | Intent normalization, hard filters, hybrid retrieval, ranking. |
| [`packages/execution`](packages/execution) | `ExecutionRuntime` protocol + `DockerOciRuntime`. |
| [`packages/verification`](packages/verification) | `Verifier` protocol + verifier registry. |
| [`packages/reputation`](packages/reputation) | Evidence, recomputed from immutable rows. |
| [`packages/security`](packages/security) | API keys, scopes, `PolicyEngine`, tenant visibility. |
| [`packages/observability`](packages/observability) | OTel tracing, structlog JSON logs, product metrics. |
| [`packages/common`](packages/common) | ids, clock, config, errors, object storage. |
| [`capabilities/examples`](capabilities/examples) | Three real, stdlib-only artifacts used by tests and benchmarks. |

**Dependency rule:** infrastructure implements the protocols in
[`packages/domain/protocols.py`](packages/domain/src/boobs_domain/protocols.py).
Never the reverse. That is what lets Docker become Firecracker, gVisor, Kata or
WASI without the product domain noticing. 🔌

### 🧰 The stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 | Typed wire contracts an agent can trust |
| Queue | Redis + arq | The API must not block on a container |
| Database | Postgres 16 + **pgvector** | Lexical `tsvector` **and** vector search in one place, with triggers doing the enforcing |
| Objects | S3 / MinIO | Execution outputs and logs |
| Embeddings | fastembed · `BAAI/bge-small-en-v1.5` (384d) | Local ONNX. No API key, no network at query time, deterministic in CI |
| Sandbox | Docker OCI, digest-pinned | Behind a protocol, so it is replaceable |
| Tooling | `uv` workspace · ruff · mypy · pytest | Fast, boring, correct |

---

## 🔎 Retrieval: how recall actually works

```
task string
    │
    ▼
① INTENT NORMALIZATION      "turn tabular comma-separated data into JSON records"
    │                                        ↓
    │                              action=convert, source=csv, target=json
    │                                        ↓
    │                                  canonical: "csv_to_json"
    ▼
② HARD FILTERS (in SQL)     visibility · not deprecated/quarantined · latest version
    │                       · os · arch · runtime · network · capabilities ⊆ offered
    ▼
③ HYBRID RETRIEVAL          Postgres ts_rank_cd  ‖  pgvector cosine distance
    ▼
④ RECIPROCAL RANK FUSION    merges two rankings without inventing a mixing ratio
    ▼
⑤ RANKING                   relevance × (floor + quality)  → score, confidence
    ▼
⑥ TOP N + recommendation    use · consider · avoid
```

**Hard filters are hard.** Anything that fails ② is not down-ranked — it is
never ranked, never returned, never executed. Offering an agent something that
*cannot* work is worse than offering nothing.

**Intent normalization** is why paraphrases collide. `"extract JSON from PDF"`
and `"convert PDF to JSON"` both normalize to `pdf_to_json` — including the
`from`-inversion trick, so the format sitting *after* "from" is understood to
be the source. Word boundaries are respected, because a naive substring search
finds `md` inside `amd64` and `text` inside `context`. 🙃

**RRF chooses candidates; it does not decide relevance.** RRF scores are
positional, so the top of any list always looks perfect — which is exactly how
a popular Experience would win a query it does not answer. Relevance is
computed separately from the actual lexical rank and cosine similarity, taking
the *stronger* claim rather than an average: a strong lexical hit and a strong
semantic hit are each sufficient evidence that this is the same task.

---

## ⚖️ Ranking: the actual numbers

All weights live in exactly one file:
[`packages/retrieval/src/boobs_retrieval/ranking.py`](packages/retrieval/src/boobs_retrieval/ranking.py).
If a recall result looks wrong, that is the only place to look. 🎯

```python
final_score = relevance × (0.45 + 0.55 × quality)
```

**Relevance multiplies. It never adds.** Evidence can only amplify a match that
is already the right thing — no quantity of proven runs should let an
Experience win a task it does not perform. 🧨

`quality` is the weighted sum of:

| Signal | Weight | What it means |
|---|---:|---|
| 🎯 confidence | **0.34** | Wilson lower bound on verified runs |
| 🧩 compatibility | **0.30** | `high` / `partial` / `none` against the caller's environment |
| 📈 usage | **0.17** | `log10(runs+1)/3`, capped — run #1 matters, run #1001 doesn't |
| ⏰ recency | **0.12** | Fresh for 24h, then decays linearly to zero over 90 days |
| ⚡ latency | **0.05** | `1/(1 + ms/5000)` — 100ms and 400ms are both just "fast" |
| ☢️ risk | **0.02** | Penalty for needing network (0.6) or capabilities (0.1 each) |

| Threshold | Value | Meaning |
|---|---:|---|
| `USE_THRESHOLD` | **0.70** | ✅ "running this is very likely cheaper than rebuilding it" |
| `CONSIDER_THRESHOLD` | **0.40** | 🤔 "have a look, but think" |
| `MIN_SCORE` | **0.30** | 🚮 below this we return *nothing* |
| `RELEVANCE_FLOOR` | **0.45** | the most a match can earn before any evidence exists |
| `INTENT_MATCH_BONUS` | **0.15** | added to *relevance* on an exact intent hit — never to evidence |

The floor is the interesting one. A **perfectly relevant but unproven**
Experience mathematically cannot reach `use`. It lands in `consider`. Because:

> Matching the task is not the same as being known to work. 🧠

And when nothing clears `MIN_SCORE`, recall returns an empty list on purpose:

> An empty answer is a correct answer. A confident wrong capability is not. 🤐

---

## 🔐 The sandbox: assume every artifact is hostile

Every artifact in the registry was uploaded by someone you have never met, to
be executed on your infrastructure, on behalf of an agent that found it via
fuzzy search. Design accordingly. 😈

[`DockerOciRuntime`](packages/execution/src/boobs_execution/docker_oci.py)
gives every execution:

| Control | Setting | Stops |
|---|---|---|
| 🌐 Network | `--network=none` | Exfiltration, C2, "just pip install one thing" |
| 📖 Filesystem | `--read-only` | Tampering with the image at runtime |
| 🎖️ Capabilities | `--cap-drop=ALL` | Everything fun |
| ⬆️ Escalation | `--security-opt=no-new-privileges` | setuid tricks |
| 👤 User | `--user=65534:65534` | Being root |
| 🧮 CPU / RAM | `--cpus`, `--memory`, `--memory-swap` (equal, so no swap escape hatch) | Neighbours getting hurt |
| 🍴 Processes | `--pids-limit` | Fork bombs |
| ⏱️ Time | wall-clock kill | Infinite loops |
| 📤 Output | byte cap + truncation flag | Log floods |
| 📂 Mounts | **none** — no host paths, no Docker socket, no ambient credentials | Host takeover |

Inputs and outputs move as **tar streams via `docker cp`**, which is precisely
why no bind mount is needed. Please do not add one. 🙏

The security tests in [`tests/security`](tests/security) run **real
containers** and try to break out: unreachable network, DNS failure, read-only
root, non-root uid, refused privilege escalation, absent Docker socket, only
`/work` writable, wall-clock timeout, fork bomb, memory hog, output flood,
output size cap.

> 🚨 **Never weaken a test in `tests/security/` to make it pass. Fix the
> sandbox.**

### 📜 The artifact contract

An image is executable by 80085 if it:

1. creates `/work` and `chown 65534:65534 /work` — the anonymous work volume
   inherits those permissions and the process runs as uid 65534;
2. reads inputs from and writes outputs to `/work`;
3. expects **no network, no root, and a read-only root filesystem**;
4. exits non-zero on failure — the floor verifier believes the exit code.

```dockerfile
FROM python:3.13-slim
RUN mkdir -p /work && chown 65534:65534 /work
COPY main.py /app/main.py
USER 65534:65534
WORKDIR /work
ENTRYPOINT []
CMD ["python", "/app/main.py"]
```

The bundled examples are deliberately **stdlib-only**: an artifact with no
dependencies has no supply chain, which is the right place to start when every
artifact is untrusted. 🧼

---

## ✅ Verification: claimed vs proven

The entire product rests on one distinction:

| Level | Means |
|---|---|
| `unverified` | Nobody checked. |
| `claimed` | An agent says it worked. Charming. 🙂 |
| `proven` | A deterministic verifier examined the stored execution artefacts and passed. |

Verifiers live in
[`packages/verification/verifiers.py`](packages/verification/src/boobs_verification/verifiers.py)
and ship with three:

| Verifier | Config | Strength |
|---|---|---|
| `exit_code` | `{expected: 0}` | 🥉 The floor: it ran to completion |
| `json_schema` | `{file, schema}` | 🥈 The output exists, is JSON, and conforms |
| `sha256` | `{file, sha256}` | 🥇 Byte-exact reproduction — the strongest claim available |

Rules, non-negotiable:

- Verifiers are **deterministic** and **recomputable** from stored execution
  artefacts. You can re-run every verdict in the system tomorrow.
- An LLM judgment may *assist* later. It must **never** be the sole source of
  truth. "An LLM said it looked right" is a vibe, not a verification. 🔮❌

Adding one is one function and one line:

```python
async def my_verifier(result: SandboxResult, config: dict) -> VerificationResult: ...

REGISTRY = {..., "my_verifier": my_verifier}
```

### 🎖️ Promotion

The **first proven execution** moves an Experience from `candidate` to
`verified`, and its level to `proven`. One proven run is the whole difference
between *"someone claims this works"* and *"this has worked"*. Quarantined
Experiences are never promoted.

---

## 🗄️ Data model and the append-only rules

| Table | Notes |
|---|---|
| `organizations`, `agents`, `api_keys` | Tenancy. Keys are SHA-256 hashed at rest. |
| `artifacts` | Digest-pinned references. |
| `experiences` | Goal, status, verification level, visibility, latest version. |
| `experience_versions` | **Append-only.** Command, env, constraints, verification spec, lineage, `tsvector`, embedding. |
| `executions` | Immutable once terminal. |
| `execution_events` | **Append-only.** The replayable narrative of a run. |
| `verifications` | **Append-only.** Every verdict ever reached. |
| `execution_stats` | Derived cache. Rebuildable from the three above. |
| `policies` | Per-experience sandbox policy overrides. |

> Append-only is enforced by **database triggers, not by convention**.
> If you need to "fix" a row, you need a new row. 🧱

Ids are prefixed and self-describing — `exp_`, `ver_`, `art_`, `exec_`, `evt_`,
`vrf_`, `org_`, `agt_`, `key_`, `pol_` — with uuid4 bodies, so they carry no
tenant information and cannot be enumerated.

**Event vocabulary:** `execution.started`, `command.started/completed/failed`,
`file.created/modified`, `test.started/completed`, `artifact.created`,
`execution.completed`, `verification.started/completed`.

### 🔑 Auth and tenancy

- Keys look like `sk_80085_…`, are generated with 32 bytes of entropy, stored
  only as a SHA-256 hash, and compared in constant time. The plaintext exists
  exactly once — in the response that created it. Lose it and it is gone. 🫠
- Scopes: `experiences:read`, `experiences:write`, `executions:run`,
  `executions:verify`, `admin`.
- Visibility: `private` (creating agent) · `organization` (owning org) ·
  `public` (everyone — this is what makes cross-agent reuse possible).
- **Mutating** an Experience requires *owning* it. **Using** one — reading,
  recalling, executing, verifying — is governed by *visibility*. That
  asymmetry is precisely what lets Agent B run Agent A's public Experience
  without being able to touch it. 🤝

Tenant isolation is one file to audit:
[`packages/security/policy.py`](packages/security/src/boobs_security/policy.py).

---

## 🚀 Quickstart

**Prerequisites:** Docker Desktop running, [`uv`](https://docs.astral.sh/uv/),
Python 3.12+.

```bash
# 1. services: postgres(+pgvector), redis, minio, local registry
docker compose up -d

# 2. install the workspace
uv sync --all-packages

# 3. schema
uv run alembic upgrade head

# 4. build the example artifacts and capture their DIGESTS
uv run python scripts/build_capabilities.py

# 5. two terminals
make api        # terminal 1 — uvicorn on :8000
make worker     # terminal 2 — MUST run on a host with Docker

# 6. two orgs + the example Experiences
uv run python scripts/seed.py
```

Then open <http://localhost:8000/docs> and poke it. 🕹️

> 🐘 **Postgres is on host port `55432`, not 5432.** A native PostgreSQL
> service commonly owns 5432 and silently wins the bind, after which you spend
> forty minutes debugging a database that isn't yours.

> 🐳 **The worker is deliberately absent from `docker-compose.yml`.** It needs
> the Docker daemon, and handing a container the host socket would undo the
> exact isolation the sandbox exists to provide. Run it on the host.

### `make` targets

| Target | Does |
|---|---|
| `make up` / `make down` | Compose services |
| `make dev` | `up` + `migrate` |
| `make api` | uvicorn, reload, :8000 |
| `make worker` | arq worker on the `80085:executions` queue |
| `make migrate` / `make seed` / `make capabilities` | Schema · demo data · build+push the examples |
| `make test` | unit + integration |
| `make test-security` / `make test-e2e` | Real containers · the cross-agent loop |
| `make lint` / `make typecheck` | ruff · mypy |
| `make benchmark` | Control vs treatment |

---

## 🔌 MCP: the three tools

MCP is the shortest path from an agent to 80085, so the tool surface is
deliberately tiny: **ask, run, contribute.** The MCP server is an HTTP client
of the API like anybody else — no database access, no privileged path. 🚪

```json
{
  "mcpServers": {
    "80085": {
      "command": "uv",
      "args": ["run", "python", "-m", "boobs_mcp.server"],
      "env": {
        "BOOBS_API_URL": "http://localhost:8000",
        "BOOBS_API_KEY": "sk_80085_…"
      }
    }
  }
}
```

| Tool | Use it when |
|---|---|
| 🔍 `recall_experience` | **Before** solving anything non-trivial. Returns ranked matches with evidence and a `recommendation`. |
| ▶️ `run_experience` | You found one. Runs an exact version in the sandbox and returns outputs **plus an independent verdict**. |
| 📝 `record_experience` | You solved something and proved it. Requires a digest-pinned reference. |

The server ships with the instruction that makes the whole thing work:

> *"Before solving a non-trivial task from scratch, call `recall_experience` to
> check whether a verified executable solution already exists."*

Put that in your agent's system prompt too. It is the single highest-leverage
line in this repository. 🎣

---

## 🌐 HTTP API

Base path `/v1`. Auth is `Authorization: Bearer sk_80085_…`.

| Method | Path | Verb it serves |
|---|---|---|
| `GET` | `/v1/health` · `/v1/ready` | Liveness · readiness (db, redis, object storage) |
| `POST` | `/v1/bootstrap` | Mint an org + agent + first key (guarded by `BOOBS_BOOTSTRAP_TOKEN`) |
| `POST` | `/v1/experiences` | **RECORD** |
| `GET` | `/v1/experiences/{id}` | **DISCOVER** |
| `POST` | `/v1/experiences/recall` | **RECALL** |
| `POST` | `/v1/experiences/{id}/execute` | **EXECUTE** (202, or 200 with `wait_seconds`) |
| `GET` | `/v1/executions/{id}` | Result, outputs, verdict |
| `GET` | `/v1/executions/{id}/events` | The append-only event stream |
| `POST` | `/v1/executions/{id}/verify` | **VERIFY** — turn an execution into evidence, or refuse to |

### 🔍 Recall

```bash
curl -s localhost:8000/v1/experiences/recall \
  -H "Authorization: Bearer $BOOBS_API_KEY" -H 'content-type: application/json' \
  -d '{
    "task": "I need to turn tabular comma-separated data into JSON records",
    "context": {"runtime": "python", "runtime_version": "3.13"},
    "constraints": {"network": false},
    "limit": 5
  }'
```

```json
{
  "matches": [{
    "experience_id": "exp_5f3c…",
    "version": 1,
    "goal": "Convert a CSV file into a normalized JSON array of objects",
    "relevance": 0.9123,
    "compatibility": "high",
    "confidence": 0.7217,
    "successful_runs": 12,
    "recommendation": "use",
    "requires_network": false,
    "evidence": { "successful_runs": 12, "failed_runs": 0, "success_rate": 1.0,
                  "median_duration_ms": 812, "distinct_organizations": 3,
                  "failure_modes": {}, "last_verified_at": "…" }
  }],
  "query_id": "qry_…",
  "took_ms": 37
}
```

Note what happened: the agent asked in *its own words* and got back an artifact
recorded in *somebody else's words*, with a compatibility grade for *its own
runtime*, and a confidence that is **not** the raw success rate. That's the
product. 🎁

### ▶️ Execute

```bash
curl -s localhost:8000/v1/experiences/exp_5f3c…/execute \
  -H "Authorization: Bearer $BOOBS_API_KEY" -H 'content-type: application/json' \
  -d '{
    "version": 1,
    "inputs": {"input.csv": "dHJhY2ssYnBtCkFjaWQgVHJheCwxMjgK"},
    "wait_seconds": 120
  }'
```

Inputs are `filename → base64`, staged into the sandbox working directory;
filenames must be plain names (no `/`, no `\`, no leading `.`). Outputs come
back the same way, alongside `stdout`, `stderr`, `exit_code`, `duration_ms`,
and a `verification` block that is *the system's* verdict, not the artifact's.

---

## 📥 Adding an Experience

```bash
# 1. write it
mkdir -p capabilities/examples/pdf_to_json   # + a Dockerfile meeting the contract

# 2. build, push, capture the digest
uv run python scripts/build_capabilities.py

# 3. record it (HTTP, or the record_experience MCP tool)
```

```jsonc
POST /v1/experiences
{
  "goal": {"statement": "Extract structured JSON from a PDF",
           "intent": "pdf_to_json", "tags": ["pdf", "json"]},
  "artifact": {"type": "oci", "reference": "registry/80085/pdf_to_json@sha256:…"},
  "command": ["python", "/app/main.py", "input.pdf", "output.json"],
  "environment": {"os": "linux", "architecture": "amd64",
                  "runtime": "python", "runtime_version": "3.13"},
  "constraints": {"network": false},
  "verification": {"verifier": "json_schema",
                   "config": {"file": "output.json", "schema": {"type": "object"}}},
  "visibility": "public"
}
```

Declaring a `verification` block is what turns future runs into **evidence**
rather than **anecdotes**. Skip it and your Experience stays permanently stuck
at `consider`, wondering why nobody calls. 📞

### 🔁 Adding an artifact runtime

Implement `ExecutionRuntime.execute(SandboxRequest) -> SandboxResult` and
construct it in `apps/worker/main.py`. Everything above it only knows the
protocol. Every sandbox limit must be enforced by the new runtime, and
`tests/security/` must pass **unchanged**. Firecracker/gVisor/Kata/WASI replace
one class and nothing else. 🧩

---

## 🧪 Tests, and the one that matters

```bash
uv run pytest tests/unit          # pure, no services
uv run pytest tests/integration   # real Postgres: triggers, tenancy, filters
uv run pytest tests/security      # real containers: escape and exhaustion
uv run pytest tests/e2e           # THE test
make benchmark                    # control vs treatment
```

Service-backed tests **skip loudly** rather than mock:

> A mocked sandbox proves nothing about isolation, and a mocked database proves
> nothing about tenancy. 🎭

### 🏆 `tests/e2e/test_cross_agent_reuse.py`

The single test the entire product is judged by:

```
Agent A  (org: acme-research)   records "Convert a CSV file into a
                                 normalized JSON array of objects"
                                 → verification proves it worked

Agent B  (org: globex-labs)     different key, different tenant, no shared
                                 context, and says instead:
                                 "I need to turn tabular comma-separated
                                  data into JSON records"
                                 → finds A's Experience
                                 → runs the exact pinned version
                                 → a verifier proves it worked again ✅

Agent C  (org: initech-data)    "parse a csv export and give me json"
                                 → finds it independently ✅

Evidence for all three runs is visible to all three. 📊
```

> **If this passes, the thesis holds: reuse was cheaper than reinvention, and
> nobody had to take anyone's word for it.**
>
> **If it fails, nothing else in this repository matters.** 🔥

---

## 📈 Benchmarks: control vs treatment

[`benchmarks/run.py`](benchmarks/run.py) measures **time to successful
outcome** — both arms must end at a *verified correct result*, or they do not
count.

| Arm | Does |
|---|---|
| 🕳️ **CONTROL** (no 80085) | `docker build --no-cache` the artifact from scratch, push it, run it sandboxed, verify the output |
| 🧠 **TREATMENT** (with 80085) | `recall` with a *paraphrase* the registry has never seen, execute the pinned version that already exists, read the verdict |

`--no-cache` is deliberate: an agent solving a problem for the first time has
no layer cache for a solution that did not exist a moment ago.

**What this measures honestly:** the cost of producing and running a *verified
executable artifact*. **What it does not measure:** an LLM token and tool-call
cost, which needs a real agent harness and real model credentials. Those
columns stay empty rather than invented. 📏

> ⚠️ **Read this before quoting numbers.** The `benchmarks/results.json`
> checked into this repo comes from a local run in which the **treatment arm
> did not pass verification** (`"verified": "NO"`, treatment slower than
> control). Treat it as a harness smoke test, not a performance claim. 80085
> makes no speed claim until that file shows verified successes on both arms.
> Fabricating a benchmark would be a *much* funnier joke than the name, and we
> are not making it. 🚫📉

---

## 🍒 About the name (yes, really)

The name is intentionally stupid. **80085** is what a calculator says when you
type it upside down, and nerds have been giggling at that since roughly the
invention of the seven-segment display.

Underneath the joke:

```
80085 → shared memory → executable experiences → verified outcomes
      → collective agent intelligence
```

The stupidest possible name for a genuinely serious piece of infrastructure.
The name gets the smile; the one-liner gets the curiosity; the product gets the
agent; the execution evidence gets the trust; the network effect gets the
company. 📈

### 🐍 …which creates exactly one engineering problem

Python identifiers cannot start with a digit. `import 80085_api` is a
`SyntaxError`, and honestly it deserves to be.

So the import namespace is `boobs_*` — the word 80085 spells on a calculator,
which is the joke the brand is built on. Everything user-facing reads `80085`.

| Layer | Name |
|---|---|
| Distributions | `80085-api`, `80085-domain`, … |
| Imports | `boobs_api`, `boobs_domain`, … |
| Env vars | `BOOBS_API_KEY`, `BOOBS_BOOTSTRAP_TOKEN`, … |
| Queue | `80085:executions` |
| Registry repos | `<registry>/80085/<capability>` |
| Containers | `80085-<execution_id>` |

Yes, your traceback will say `boobs_domain.entities`. Yes, it will happen
during a demo. Yes, that is the price of admission. 🎟️😌

---

## ⚙️ Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres DSN (`postgresql+asyncpg://…`) |
| `REDIS_URL` | Queue |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Execution outputs and logs |
| `ARTIFACT_REGISTRY` | Registry that `scripts/build_capabilities.py` pushes to |
| `SANDBOX_CPU`, `SANDBOX_MEMORY_MB`, `SANDBOX_TMPFS_MB`, `SANDBOX_TIMEOUT_SECONDS`, `SANDBOX_PIDS`, `SANDBOX_MAX_OUTPUT_BYTES` | Sandbox policy defaults, overridable per Experience |
| `BOOBS_BOOTSTRAP_TOKEN` | Guards `/v1/bootstrap`, which mints API keys |
| `BOOBS_EMBEDDER` | `auto` (default) · `fastembed` · `hashing` |
| `BOOBS_API_KEY`, `BOOBS_API_URL` | Used by the MCP server to call the API |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional; unset keeps tracing in-process |

Start from [`.env.example`](.env.example). Never commit `.env`.

> 🧠 `BOOBS_EMBEDDER=auto` falls back to a non-semantic hashing embedder when
> the ONNX model cannot load — and **says so loudly in the logs**. Silent
> degradation of recall quality is the failure mode that would be hardest to
> notice from the outside. Lexical retrieval carries the query on its own in
> the meantime.

> 🔒 **Never** put secrets in source, Experience metadata, embeddings,
> execution logs, manifests, or Git. The registry is designed to be shared;
> assume everything in it will be.

---

## 🗺️ Roadmap

**Phase 0 — Proof** ✅ *(where we are)*
Record → recall → execute → verify → evidence, proven by the cross-agent test.

**Phase 1 — Reach**
- 🌍 `apps/web`: public discovery surface, `llms.txt`, integration docs
- 🤖 Agent SDK, so `recall` is one line in any harness
- 📚 A real corpus of public Experiences beyond three CSV toys

**Phase 2 — Depth**
- 🧬 **Experience Graph** — the `lineage` fields already exist and are unused
- 🧩 **Composability** — Experiences that call Experiences
- 🕵️ **Automatic extraction** — mine a solved task into a candidate Experience
- ⏳ **Staleness sweeps** — re-verify on a schedule, quarantine what rots
- 🔧 **Autonomous improvement** — propose a better version, prove it, supersede

**Phase 3 — Everywhere**
Coding → DevOps → data → browser agents → business agents → robotics.
Agents stop *generating* solutions and start *inheriting* them. 🧠→🧠

---

## 🙅 Non-goals

- ❌ **Not a coding agent.** It remembers; it does not write.
- ❌ **Not a chat app.** There is no chat. There is a rank and a verdict.
- ❌ **Not a container registry.** Registries store bytes; we store *warranted claims about* bytes.
- ❌ **Not a rating system.** No stars, no upvotes, no "was this helpful?" buttons.
- ❌ **Not Skynet.** The MVP is judged by one question: *can Agent B reuse
  something Agent A already figured out?* If yes, we have something. If no,
  **do not build another feature — figure out why.** 🔍

---

## ❓ FAQ

**Is the name a problem?**
Professionally, occasionally. Strategically, no: you have already remembered
it, which is more than you can say for the last twelve infrastructure startups
you read about. 🧠

**Why not just let agents share prompts?**
Because a prompt is a wish and an artifact is a fact. You cannot compute a
success rate for a wish. 🌠

**What if someone uploads something malicious?**
Assume they will. That is why the sandbox has no network, no root, no
capabilities, no writable root filesystem, no host mounts, no Docker socket,
and a wall-clock kill — and why `tests/security/` tries to break it on every
run. 🛡️

**Why is a brand-new Experience never recommended?**
Because relevance is not evidence. `RELEVANCE_FLOOR = 0.45` makes that
arithmetic rather than policy. Run it a few times and it earns its way to
`use`. 🎓

**Why does confidence say 20.7% when it has never failed?**
Because it has run once. Wilson is right and your intuition is wrong. 📐

**Can it store something other than containers?**
Yes — that is the design. `ArtifactType` is an enum, `ExecutionRuntime` is a
protocol, and the sandbox is one swappable class. CLI, WASM, MCP tool, patch,
workflow: the Experience is the product, the artifact is just how it runs. 🔌

**Is `boobs_domain` really an import namespace in a production codebase?**
Yes. 🫡

---

## 🤝 Contributing

Read [`AGENTS.md`](AGENTS.md) first — it is the operating manual, written for
coding agents, and it states the rules that are not obvious from the code.
[`80085-ai-MASTER-BUILD-DESIGN.md`](80085-ai-MASTER-BUILD-DESIGN.md) is the
full specification that the section numbers scattered through the source refer
to.

The short version:

**Always** — inspect before modifying · small changes · run tests after
meaningful ones · lint and type-check · preserve tenant isolation · treat
artifacts as hostile · record uncertainty.

**Never** — invent credentials or infrastructure · expose secrets · disable
security to make tests pass · claim a deployment succeeded without checking ·
claim tests passed without running them · add dependencies without need ·
build speculative infrastructure before proving value.

Deliberate shortcuts are marked with a `ponytail:` comment naming the ceiling
and the upgrade path. Grep for them before assuming something is an oversight:

```bash
grep -rn "ponytail:" packages apps
```

🔐 **Security issues:** please report privately rather than opening a public
issue.

---

## 📊 Status, honest edition

| Thing | State |
|---|---|
| Record → recall → execute → verify → evidence | ✅ Implemented end to end |
| Cross-agent reuse test | ✅ Exists, and is the acceptance criterion |
| Sandbox isolation suite | ✅ Real containers, real escape attempts |
| Example capabilities | ✅ Three, stdlib-only |
| Benchmark harness | ⚠️ Runs; the checked-in results are **not** a performance claim |
| `apps/web` public surface | 🚧 Specified, not built |
| `docs/` | 🚧 Empty; `AGENTS.md` + the spec are the real documentation |
| License | 🚧 None yet — all rights reserved until a `LICENSE` lands |

---

<div align="center">

## 🧠 80085.ai

**Remember what works. Reuse it everywhere.**

Agents do not just have tools — they have experience.
They do not just generate solutions — they inherit them.
They do not just get smarter individually — they get smarter together.

*Do not reinvent the wheel.*
*Do not reinvent the boobs either.* 🤖🍈🍈

</div>
