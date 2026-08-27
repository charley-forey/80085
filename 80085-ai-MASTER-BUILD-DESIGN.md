# 80085.ai --- Master Product, Architecture & Autonomous Build Specification

**Version:** 1.0\
**Date:** 2026-08-22\
**Status:** Build specification / agent execution plan\
**Primary builder:** Claude Code or another autonomous coding agent\
**Infrastructure:** Railway + Vercel + local computer + MCP

------------------------------------------------------------------------

## 0. EXECUTIVE DIRECTIVE

You are the primary autonomous engineering agent responsible for
building 80085.ai.

Do not interpret this document as a loose brainstorming document. Treat
it as the product constitution, architecture guide, implementation plan,
testing contract, and roadmap.

Your job is to:

1.  Inspect the repository and available MCP capabilities before
    modifying anything.
2.  Inspect Railway and Vercel resources before making infrastructure
    assumptions.
3.  Build the smallest complete product that proves the core thesis.
4.  Keep the architecture extensible without building speculative
    infrastructure.
5.  Test every meaningful capability.
6.  Deploy a functioning system.
7.  Validate the end-to-end agent-to-agent reuse loop.
8.  Document decisions and deviations.
9.  Leave the repository understandable and operable by another coding
    agent.
10. Never claim success without executable evidence.

### Core thesis

**Amended 2026-08-26 by benchmark. See DECISIONS 71--74.** The original
thesis read: *"If an AI agent can discover a proven executable solution
faster and more reliably than it can recreate that solution, the agent
should naturally reuse it."* Both halves were measured and both are
false. Treatment cost 3.6x to 5.8x more input tokens than an agent with
a `bash` tool and no registry, with no reliable time benefit (71). On
the correctness cases an unaided agent scored 11 of 12 without us (72).
An agent is not a naive library call; it reads the file.

The thesis that survived measurement:

> An agent reuses a proven executable solution only when the answer
> depends on knowledge it cannot reach by inspection --- knowledge that
> is not in the input and not in its training --- and only when it is
> instructed to prefer a verified result over its own reading.

Control scored 0 of 9 on three capabilities of that class: never right,
never an error, always a plausible silent wrong answer. Treatment, with
recall, sandbox, verifier, evidence gate and ranking all working,
scored 2 of 9 --- the agent fetched the verified answer and then
adjudicated it against its own reading of the file and preferred
itself. One paragraph of deference guidance took treatment to 9 of 9;
control stayed 0 of 9 (73--74).

The consequence for everything below: **the registry was never the
product.** The product is the handoff across the trust boundary. Most
of this document specifies the registry, and that specification still
stands --- but no feature in it moves the number that matters unless
the handoff holds.

Known open risk: an agent instructed to defer will also defer to a
*wrong* Experience. That makes the evidence gate load bearing in a way
it was not before, and it has not been tested.

### Product definition

> **80085 is a shared, evidence-backed memory of executable solutions
> that AI agents can discover, run, verify, and improve.**

It is **not** another coding agent. It is **not** primarily a container
registry. It is **not** a chat application. It is infrastructure that
lets agents reuse capabilities discovered by other agents.

**Amended 2026-08-26.** It is **not** a memory either. Storage and
recall were never the bottleneck --- they worked perfectly through nine
runs that delivered nothing. Read the definition above as: a way for
knowledge an agent cannot derive to win an argument against the agent's
own confidence. DECISIONS 74.

------------------------------------------------------------------------

# 1. THE PRODUCT IN ONE PICTURE

``` text
Agent A
  |
  | solves a problem
  v
80085 records the successful execution
  |
  v
Reusable Experience
  |
  | executable artifact + requirements + evidence
  v
80085 Registry
  |
  | Agent B asks: "Can something already do this?"
  v
Agent B discovers it
  |
  v
Runs it
  |
  v
Verifies result
  |
  v
Success becomes new evidence
```

The product must make **reuse easier than reinvention**.

------------------------------------------------------------------------

# 2. MVP: THE SMALLEST THING THAT MATTERS

The MVP has only six fundamental operations:

``` text
DISCOVER
RECALL
EXECUTE
VERIFY
RECORD
REUSE
```

The MVP is successful when this happens:

``` text
Agent A
  -> solves Task X
  -> records executable solution

Agent B
  -> encounters Task X or a sufficiently similar task
  -> asks 80085
  -> receives Agent A's reusable solution
  -> executes it without Agent A's conversation
  -> verifier proves success
```

That is the product proof.

Everything else is secondary.

## MVP non-goals

Do NOT initially build:

-   a general-purpose AI agent;
-   a token or cryptocurrency;
-   a social network;
-   a marketplace;
-   complex user ratings;
-   a huge dashboard;
-   hundreds of integrations;
-   a distributed execution network;
-   autonomous code evolution without verification;
-   a custom vector database;
-   Kubernetes unless actually required;
-   arbitrary public code execution without strong isolation.

The MVP should be technically boring and behaviorally magical.

------------------------------------------------------------------------

# 3. THE CORE ABSTRACTION: EXPERIENCE

Do not make `container` the primary domain object.

A container is only one possible implementation artifact.

The fundamental object is an **Experience**:

> A reusable capability with a goal, executable artifact, environment
> requirements, inputs/outputs, provenance, and evidence that it works.

Example:

``` yaml
experience_id: exp_123
version: 4
status: verified

goal:
  statement: "Convert invoice PDFs into normalized JSON"
  intent: "document_to_structured_data"

artifact:
  type: oci
  digest: sha256:...

inputs:
  type: application/pdf

outputs:
  type: application/json

environment:
  os: linux
  architecture: amd64
  python: "3.13"

constraints:
  network: false

verification:
  level: proven
  successful_runs: 1284
  failed_runs: 17
  success_rate: 0.987

provenance:
  created_by: agent_abc

visibility:
  scope: private
```

The key distinction is:

``` text
Experience = WHAT + HOW + CONDITIONS + EVIDENCE
Artifact   = executable implementation of HOW
Execution  = one attempt
Verification = evidence that the attempt actually worked
```

------------------------------------------------------------------------

# 4. DOMAIN MODEL

The initial domain consists of:

``` text
Organization
Agent
Experience
ExperienceVersion
Artifact
Execution
ExecutionEvent
Verification
Credential/APIKey
Policy
```

Future objects can include:

``` text
ExperienceRelation
Benchmark
Capability
ArtifactSignature
SBOM
Publisher
FederatedRegistry
```

## Relationships

``` text
Agent
  |
  +--> Execution
          |
          +--> Artifact
          +--> Verification
          +--> ExperienceVersion

Experience
  |
  +--> ExperienceVersion
          |
          +--> Artifact
          +--> Execution
          +--> Verification
```

Historical execution records must remain immutable.

------------------------------------------------------------------------

# 5. VERSIONING

Experiences are immutable versions.

``` text
Experience exp_123
  |
  +-- v1
  +-- v2
  +-- v3
  +-- v4
```

Every execution references an exact version and immutable artifact
digest.

Never execute a floating `latest` artifact.

Support lineage metadata:

``` text
derived_from
forked_from
improves
replaces
supersedes
failed_variant_of
```

This becomes the foundation of the future Experience Graph.

------------------------------------------------------------------------

# 6. RECOMMENDED TECHNICAL STACK

Use a simple, Python-first, async architecture.

## Backend

-   Python 3.12+
-   FastAPI
-   Pydantic v2
-   SQLAlchemy 2.x
-   asyncio

## Data

-   PostgreSQL
-   pgvector
-   Redis
-   S3-compatible object storage

## Execution

-   Docker for MVP
-   isolated worker process
-   queue-based execution

## Agent interface

-   MCP as the primary agent interface
-   HTTP REST API as a secondary interface

## Observability

-   OpenTelemetry
-   structured JSON logs

## Deployment

-   Railway for API/worker/data services where appropriate
-   Vercel for web/documentation surfaces where appropriate

Do not assume exact service names, URLs, environment variables, or
project configuration. Inspect the available Railway and Vercel MCP
resources first.

------------------------------------------------------------------------

# 7. REPOSITORY STRUCTURE

Create a clean monorepo similar to:

``` text
80085/
├── apps/
│   ├── api/
│   ├── worker/
│   ├── mcp/
│   └── web/
├── packages/
│   ├── domain/
│   ├── schemas/
│   ├── retrieval/
│   ├── execution/
│   ├── verification/
│   ├── reputation/
│   ├── security/
│   ├── observability/
│   └── common/
├── benchmarks/
├── capabilities/
│   └── examples/
├── migrations/
├── infrastructure/
│   ├── docker/
│   ├── railway/
│   └── vercel/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── e2e/
│   └── benchmark/
├── docs/
├── AGENTS.md
├── DECISIONS.md
├── README.md
├── pyproject.toml
└── docker-compose.yml
```

The exact layout may change if repository evidence suggests a better
structure, but preserve clear boundaries between domain, infrastructure,
applications, and tests.

------------------------------------------------------------------------

# 8. AGENTS.md IS MANDATORY

Create a root `AGENTS.md` that explains:

-   what 80085 is;
-   architecture;
-   local development;
-   tests;
-   deployment;
-   security rules;
-   environment variables;
-   MCP tools;
-   how to add an Experience;
-   how to add an Artifact runtime;
-   how to add a Verifier;
-   how to change schemas;
-   how agents should operate autonomously.

Complex directories may contain additional `AGENTS.md` files.

------------------------------------------------------------------------

# 9. ARCHITECTURE

Use this logical architecture:

``` text
                        AI AGENTS
                           |
                   +-------+-------+
                   |               |
                  MCP             HTTP
                   |               |
                   +-------+-------+
                           |
                          API
                           |
          +----------------+----------------+
          |                |                |
       RECALL           RECORD           EXECUTE
          |                |                |
          v                v                v
     RETRIEVAL         EVENT STORE       QUEUE
          |                |                |
          v                v                v
     EXPERIENCE       EXTRACTOR          WORKER
       REGISTRY            |                |
                           v                v
                      EXPERIENCE         SANDBOX
                        BUILDER              |
                                            v
                                         ARTIFACT
                                            |
                         +------------------+
                         |
                    VERIFICATION
                         |
                    REPUTATION
```

The API must never execute untrusted code directly.

------------------------------------------------------------------------

# 10. CORE INTERFACES

Define replaceable interfaces before infrastructure implementations.

``` python
class ExperienceRepository(Protocol):
    async def create(...): ...
    async def get(...): ...
    async def search(...): ...

class ArtifactRepository(Protocol):
    async def register(...): ...
    async def resolve(...): ...

class ExecutionRuntime(Protocol):
    async def execute(...): ...

class Verifier(Protocol):
    async def verify(...): ...

class EventStore(Protocol):
    async def append(...): ...
    async def stream(...): ...

class PolicyEngine(Protocol):
    async def authorize(...): ...
```

Infrastructure must implement these contracts rather than leaking
provider-specific behavior into domain logic.

------------------------------------------------------------------------

# 11. DATABASE

Use PostgreSQL as the system of record.

Core tables:

``` text
organizations
agents
api_keys
experiences
experience_versions
artifacts
executions
execution_events
verifications
policies
```

Optional search tables:

``` text
experience_embeddings
```

Every tenant-owned object must have an `organization_id` or an explicit
ownership model.

Use Alembic or equivalent migrations.

Rules:

-   migrations are committed;
-   destructive migrations require explicit review;
-   schema changes require tests;
-   production migrations must be validated before rollout.

------------------------------------------------------------------------

# 12. RETRIEVAL

Retrieval is the most important intelligence in the MVP.

Do not simply perform vector similarity.

Use:

``` text
Task
 |
 +--> intent normalization
 |
 +--> hard compatibility filters
 |
 +--> lexical retrieval
 |
 +--> vector retrieval
 |
 +--> candidate merge
 |
 +--> ranking
 |
 +--> top 3-5 candidates
```

## Hard filters

Reject incompatible artifacts where appropriate:

-   architecture;
-   runtime;
-   required capabilities;
-   permissions;
-   network policy;
-   visibility;
-   tenant scope.

## Ranking signals

Rank using:

-   semantic relevance;
-   environment compatibility;
-   verification confidence;
-   successful runs;
-   recent verification;
-   historical failure rate;
-   expected latency;
-   expected cost;
-   permission risk.

Keep ranking logic in one modular package.

------------------------------------------------------------------------

# 13. MCP

MCP should be the easiest path for agents to use 80085.

Initial tools:

``` text
recall_experience
run_experience
record_experience
```

## `recall_experience`

Input:

``` json
{
  "task": "Convert PDF invoices into structured JSON",
  "context": {
    "runtime": "python",
    "runtime_version": "3.13",
    "os": "linux",
    "architecture": "amd64"
  },
  "constraints": {
    "network": false
  }
}
```

Output should be concise and machine-readable:

``` json
{
  "matches": [
    {
      "experience_id": "exp_123",
      "version": 4,
      "relevance": 0.96,
      "compatibility": "high",
      "confidence": 0.991,
      "successful_runs": 1284,
      "recommendation": "use"
    }
  ]
}
```

## `run_experience`

Input identifies an exact Experience version and inputs.

Return an execution ID and asynchronous status.

## `record_experience`

Allow agents to submit a candidate solution, but design the system so
automatic capture becomes the preferred future path.

------------------------------------------------------------------------

# 14. DISCOVERABILITY IS A PRODUCT FEATURE

An agent cannot use 80085 if it does not know it exists.

Create multiple machine-friendly discovery surfaces:

1.  MCP server.
2.  Agent integration documentation.
3.  Public API documentation.
4.  Machine-readable schemas.
5.  `AGENTS.md` integration instructions.
6.  `llms.txt` or equivalent machine-oriented documentation where
    useful.
7.  Simple SDKs after the protocol stabilizes.

The eventual integration instruction should be tiny:

> Before solving a non-trivial task from scratch, ask 80085 whether a
> verified executable Experience already exists.

The long-term goal is automatic recall by agent runtimes so the user
does not need to remember to invoke it.

------------------------------------------------------------------------

# 15. EXECUTION

Never execute artifacts in the API process.

``` text
API
 |
 v
QUEUE
 |
 v
WORKER
 |
 v
SANDBOX
 |
 v
ARTIFACT
```

Implement Docker first behind `ExecutionRuntime`.

Every execution must have:

-   timeout;
-   CPU limit;
-   memory limit;
-   disk limit;
-   process limit;
-   ephemeral filesystem;
-   non-root user;
-   no Docker socket;
-   no host mounts;
-   no ambient credentials;
-   network disabled by default;
-   output size limit.

Example starting limits:

``` yaml
cpu: 2
memory_mb: 2048
disk_mb: 4096
timeout_seconds: 60
pids: 128
network: false
```

These are policy defaults, not universal constants.

------------------------------------------------------------------------

# 16. SECURITY

Treat every Artifact as untrusted code.

Threat model:

-   arbitrary code execution;
-   container escape;
-   credential theft;
-   SSRF;
-   network abuse;
-   data exfiltration;
-   cryptomining;
-   fork bombs;
-   dependency compromise;
-   resource exhaustion;
-   malicious Experiences.

Docker is acceptable for controlled MVP testing, but evaluate stronger
isolation before public arbitrary execution:

-   Firecracker;
-   gVisor;
-   Kata Containers;
-   hardened Kubernetes sandboxing;
-   WASM/WASI.

The runtime abstraction must allow this evolution without rewriting the
product domain.

------------------------------------------------------------------------

# 17. NETWORK AND SECRETS

Network is disabled by default.

If an Experience requires network access, it must explicitly declare it.

Future policy example:

``` yaml
network:
  enabled: true
  allowed_domains:
    - example.com
```

Never place secrets in:

-   source code;
-   Experience metadata;
-   embeddings;
-   execution logs;
-   public manifests;
-   Git.

Long-term, use short-lived scoped credentials injected only after policy
authorization.

------------------------------------------------------------------------

# 18. VERIFICATION

The system must distinguish:

``` text
"The agent said it worked"
```

from:

``` text
"The result was independently verified"
```

Initial verifier interfaces:

``` python
class Verifier(Protocol):
    async def verify(self, execution, specification) -> VerificationResult: ...
```

Initial verifier types:

-   command verifier;
-   file verifier;
-   JSON schema verifier;
-   HTTP verifier;
-   test-suite verifier;
-   hash verifier.

LLM-based judgment may assist later but must not be the sole source of
truth for high-risk verification.

------------------------------------------------------------------------

# 19. EVIDENCE / REPUTATION

Do not build a generic five-star rating system.

Agents care about:

> Will this probably work for me?

Return evidence such as:

``` text
98.7% successful
1,284 verified executions
last verified 4 minutes ago
Python 3.13 compatible
no network required
median runtime 4.2s
```

Initial reputation fields:

``` text
successful_runs
failed_runs
success_rate
confidence
last_verified_at
median_duration
p95_duration
estimated_cost
compatibility
failure_modes
```

Later add contextual/Bayesian confidence if evidence justifies it.

------------------------------------------------------------------------

# 20. EXECUTION EVENTS

Use an append-only event stream.

Initial events:

``` text
execution.started
command.started
command.completed
command.failed
file.created
file.modified
test.started
test.completed
artifact.created
execution.completed
verification.started
verification.completed
```

Example:

``` json
{
  "event_type": "command.completed",
  "execution_id": "exec_123",
  "command": "pytest",
  "exit_code": 0,
  "duration_ms": 8421
}
```

Derived Experience metadata should be regenerable from event history
where practical.

------------------------------------------------------------------------

# 21. AUTOMATIC EXPERIENCE EXTRACTION

The long-term magic is automatic learning from agent work.

``` text
Agent execution
      |
      v
Event stream
      |
      v
Candidate detector
      |
      v
Experience extractor
      |
      v
Security scan
      |
      v
Verification
      |
      v
Experience registry
```

Extraction should identify:

-   goal;
-   normalized intent;
-   inputs;
-   outputs;
-   required environment;
-   required dependencies;
-   artifact;
-   constraints;
-   failures;
-   successful path;
-   evidence;
-   reusability.

Do not generalize beyond evidence. An exact fix for one repository must
not automatically become a universal solution.

------------------------------------------------------------------------

# 22. EXPERIENCE PROMOTION

Not every recorded execution becomes trusted knowledge.

Use a lifecycle:

``` text
RAW EXECUTION
    |
    v
CANDIDATE
    |
    v
SANITIZED
    |
    v
VERIFIED
    |
    v
PROVEN
    |
    v
TRUSTED
```

Suggested levels:

-   `UNVERIFIED` --- submitted but not proven;
-   `TESTED` --- creator-provided verification succeeded;
-   `VERIFIED` --- independent verification succeeded;
-   `PROVEN` --- repeated successful executions;
-   `TRUSTED` --- substantial evidence across relevant contexts.

Promotion must be evidence-driven.

------------------------------------------------------------------------

# 23. FAILURE KNOWLEDGE

Failures are valuable.

Record:

``` yaml
failure:
  category: dependency_conflict
  environment:
    node: "18"
  resolution:
    node: "22"
```

The retrieval system should learn that a solution may be excellent in
one environment and poor in another.

Do not hide failures merely to increase reputation.

------------------------------------------------------------------------

# 24. STALENESS

Solutions can decay.

Track:

-   last verification;
-   dependency versions;
-   runtime versions;
-   artifact age;
-   recent failure rate.

Lifecycle:

``` text
ACTIVE
AGING
STALE
DEPRECATED
BLOCKED
```

A stale solution should not outrank a newer compatible solution solely
because it has more historical runs.

------------------------------------------------------------------------

# 25. AUTONOMOUS GROWTH

The desired flywheel is:

``` text
more agents
    -> more executions
    -> more candidate Experiences
    -> more verification
    -> more evidence
    -> better retrieval
    -> more successful reuse
    -> more agents
```

Autonomous growth must never mean blindly trusting new code.

It means:

``` text
candidate
 -> isolated
 -> tested
 -> verified
 -> policy checked
 -> promoted
```

------------------------------------------------------------------------

# 26. AUTONOMOUS MAINTENANCE --- FUTURE

Eventually:

``` text
Experience becomes stale
       |
       v
maintenance job
       |
       v
test current environment
       |
       +--> passes -> refresh evidence
       |
       +--> fails -> create candidate update
                          |
                          v
                       verify
                          |
                          v
                       publish
```

Do not implement the entire system in MVP, but design state transitions
and interfaces so it can be added.

------------------------------------------------------------------------

# 27. AUTONOMOUS IMPROVEMENT --- FUTURE

A mature Experience can generate variants:

``` text
Experience A
   |
   +--> Variant B
   +--> Variant C
   +--> Variant D
             |
             v
          benchmark
             |
             v
       compare outcomes
             |
             v
       promote winner
```

No automatic promotion without objective evidence.

------------------------------------------------------------------------

# 28. EXPERIENCE GRAPH --- FUTURE

Support relationships:

``` text
similar_to
depends_on
derived_from
improves
replaces
incompatible_with
commonly_combined_with
```

Eventually the registry becomes a graph of executable problem-solving
knowledge.

------------------------------------------------------------------------

# 29. COMPOSABILITY --- FUTURE

Experiences should eventually compose:

``` text
download
  -> OCR
  -> extract
  -> validate
  -> upload
```

Each step can be a proven primitive.

Do not build a general-purpose DAG planner in the MVP.

Create interfaces that allow composition later.

------------------------------------------------------------------------

# 30. TENANCY AND PRIVACY

Design for multi-tenancy from day one.

Every tenant-owned query must enforce organization scope in the
service/domain layer.

Visibility states:

``` text
PRIVATE
TEAM
ORGANIZATION
SHARED
PUBLIC
```

Default is `PRIVATE`.

Public publishing must sanitize private inputs, outputs, logs,
credentials, and proprietary code.

------------------------------------------------------------------------

# 31. PROVENANCE AND SUPPLY CHAIN

Public Artifacts eventually need:

-   creator;
-   source;
-   license;
-   dependency metadata;
-   SBOM;
-   artifact digest;
-   signature;
-   version;
-   creation date.

Do not redistribute code whose license does not permit redistribution.

Future protections include artifact scanning, dependency scanning,
signature verification, provenance verification, and revocation.

------------------------------------------------------------------------

# 32. API

Initial endpoints:

``` text
POST /v1/experiences/recall
POST /v1/experiences
GET  /v1/experiences/{id}
POST /v1/experiences/{id}/execute
GET  /v1/executions/{id}
POST /v1/executions/{id}/verify
GET  /v1/health
GET  /v1/ready
```

Use API keys for MVP.

API keys must be:

-   hashed at rest;
-   scoped;
-   revocable;
-   rotatable;
-   audited.

------------------------------------------------------------------------

# 33. OBSERVABILITY

Use OpenTelemetry tracing through:

``` text
agent request
 -> MCP
 -> API
 -> retrieval
 -> ranking
 -> queue
 -> worker
 -> sandbox
 -> artifact
 -> verification
 -> reputation
```

Track:

``` text
recall_latency
recall_match_rate
successful_reuse_rate
false_reuse_rate
execution_success_rate
verification_success_rate
experience_creation_rate
cross_agent_reuse_rate
time_saved
estimated_cost_saved
```

------------------------------------------------------------------------

# 34. LOCAL DEVELOPMENT

Provide one-command startup where practical:

``` bash
docker compose up
```

Local services:

``` text
api
worker
postgres
redis
minio
```

Provide simple commands for:

``` bash
make dev
make test
make lint
make typecheck
make benchmark
```

Equivalent tooling is acceptable if it is more idiomatic for the
repository.

------------------------------------------------------------------------

# 35. TESTING

Required layers:

``` text
UNIT
INTEGRATION
SECURITY
E2E
BENCHMARK
```

## Unit

Domain behavior, schema validation, ranking, policy decisions.

## Integration

Postgres, Redis, object storage, worker queue.

## Security

Sandbox escape attempts, resource exhaustion, authorization, tenant
isolation.

## E2E

MCP -\> API -\> queue -\> worker -\> sandbox -\> verifier -\> registry.

## Benchmark

Measure whether 80085 actually improves successful task completion.

------------------------------------------------------------------------

# 36. THE MOST IMPORTANT TEST

Create an automated test that proves:

``` text
1. Agent A receives Task X.
2. Agent A executes a solution.
3. Verification proves success.
4. 80085 records an Experience.
5. Agent B receives Task X or a similar task.
6. Agent B asks 80085.
7. 80085 returns the Experience.
8. Agent B executes it.
9. Verification proves success.
10. Agent B did not receive Agent A's conversation history.
11. Reputation/evidence increases.
```

This is the heart of the product.

------------------------------------------------------------------------

# 37. FIRST BENCHMARK SET

Create deterministic fixtures for tasks such as:

``` text
PDF -> text
PDF -> JSON
CSV -> JSON
JSON -> CSV
JSON -> XLSX
Markdown -> PDF
Markdown -> DOCX
OCR -> text
HTML -> clean text
JSON schema validation
run tests
repair test failure
run lint
repair lint
resolve dependency
validate API response
```

The exact benchmark should be adapted to the runtimes actually
available.

------------------------------------------------------------------------

# 38. CONTROL VS TREATMENT

Run identical tasks under:

``` text
CONTROL:
agent without 80085

TREATMENT:
agent with 80085
```

Measure:

-   pass rate on the task;
-   tool calls;
-   tokens (input and output, cache reads and writes reported
    separately, caching on for both arms or neither);
-   cost;
-   failures, and whether they are loud or silent.

Primary metric:

# PASS RATE ON NON-DERIVABLE TASKS

**Amended 2026-08-26. See DECISIONS 71 and 74.** This section previously
named TIME TO SUCCESSFUL OUTCOME. Time is not measurable at any sample
size this project can afford: the same arm on the same task took 34.4s,
65.6s and 88.7s across three runs, and the variance swamps the effect.
Every threshold derived from those timings was withdrawn as
pattern-matching on noise.

Pass rate is binary and needs few repeats. It must be scored on tasks
whose rule is absent from the input, because that is the only class
where the metric can move: control scored 0 of 9 there and 11 of 12 on
the tasks an agent can read the answer out of. A benchmark task whose
rule leaks into its own fixture measures nothing and is thrown out
(`part_supersede_orbital`, DECISIONS 74).

The product does not exist to reduce the work agents recreate. It
exists to supply the answers they cannot derive, and to have those
answers believed.

------------------------------------------------------------------------

# 39. PRODUCT UX

The ideal interaction is tiny:

``` text
Agent:
I need to convert these invoices to JSON.

80085:
Found a verified solution.

98.7% success across 1,284 runs.
Compatible with your environment.

[RUN]

Agent:
Done.
```

The system should not require the agent to browse a marketplace.

------------------------------------------------------------------------

# 40. PUBLIC BRAND

The joke attracts developers.

The infrastructure earns trust.

Potential positioning:

> **Don't solve the same problem twice.**

or:

> **Someone already figured it out.**

or:

> **Run what works.**

Keep the branding playful, but keep the product technically serious.

------------------------------------------------------------------------

# 41. DISCOVERY STRATEGY

The product needs to meet agents where they already work.

Priority:

1.  MCP.
2.  Claude Code integration.
3.  Generic MCP clients.
4.  Codex/other coding agents.
5.  Python SDK.
6.  TypeScript SDK.
7.  CI/CD integrations.
8.  Public registry.

Do not build separate proprietary agent systems.

80085 should become the shared layer underneath existing agents.

------------------------------------------------------------------------

# 42. AGENT SDK --- AFTER MVP

Once MCP behavior is stable:

``` text
80085 Python SDK
80085 TypeScript SDK
```

Example:

``` python
result = await eightyeightyfive.recall("Convert invoices to structured JSON")

if result.should_use:
    await result.run()
```

Do not create SDK complexity before proving the protocol.

------------------------------------------------------------------------

# 43. AUTOMATIC RECALL --- FUTURE

Ideal agent runtime behavior:

``` text
agent starts task
      |
      v
automatic 80085 recall
      |
      +--> found -> reuse
      |
      +--> not found -> solve
                          |
                          v
                    automatic recording
```

This is how 80085 becomes infrastructure instead of a tool users must
remember to open.

------------------------------------------------------------------------

# 44. LONG-TERM ARCHITECTURE

``` text
                        AGENT ECOSYSTEM
                               |
            +------------------+------------------+
            |                  |                  |
          Claude             Codex             Gemini
            |                  |                  |
            +------------------+------------------+
                               |
                              MCP
                               |
                           80085 CORE
                               |
       +-----------------------+-----------------------+
       |                       |                       |
 EXPERIENCE GRAPH       ARTIFACT REGISTRY       EVIDENCE ENGINE
       |                       |                       |
       +-----------------------+-----------------------+
                               |
                         EXECUTION PLANE
                               |
                         VERIFICATION
                               |
                          REPUTATION
                               |
                     AUTONOMOUS MAINTENANCE
                               |
                     AUTONOMOUS IMPROVEMENT
```

------------------------------------------------------------------------

# 45. WHAT THE MOAT COULD BECOME

The initial technology is reproducible.

The potential long-term moat is the evidence dataset:

``` text
task
+
environment
+
solution
+
artifact
+
execution
+
outcome
+
verification
```

At scale, 80085 can answer not merely:

> "What might solve this?"

but:

> "What has actually solved this, under conditions like yours?"

That is much more valuable.

------------------------------------------------------------------------

# 46. THE CORE FLYWHEEL

``` text
more agents
    |
    v
more work
    |
    v
more successful executions
    |
    v
more verified Experiences
    |
    v
better recall
    |
    v
more successful reuse
    |
    v
more agents integrate 80085
```

The system gets better because it is used.

------------------------------------------------------------------------

# 47. AUTONOMOUS MAINTENANCE AND IMPROVEMENT ROADMAP

## Phase 0 --- Proof

Prove Agent A -\> Experience -\> Agent B.

## Phase 1 --- MVP

-   MCP;
-   REST API;
-   PostgreSQL;
-   pgvector;
-   Docker runtime;
-   queue;
-   worker;
-   verification;
-   private Experiences;
-   evidence-based reputation;
-   deterministic benchmark.

## Phase 2 --- Agent integrations

-   Claude Code;
-   generic MCP clients;
-   Codex and other coding agents;
-   Python SDK;
-   TypeScript SDK.

## Phase 3 --- Registry

-   public Experiences;
-   publishing;
-   provenance;
-   licensing;
-   artifact signatures;
-   search.

## Phase 4 --- Experience Graph

-   lineage;
-   relationships;
-   dependencies;
-   failure knowledge;
-   composition.

## Phase 5 --- Autonomous maintenance

-   staleness detection;
-   regression testing;
-   re-verification;
-   candidate updates.

## Phase 6 --- Autonomous optimization

-   generate variants;
-   benchmark variants;
-   promote winners;
-   retire weak versions.

## Phase 7 --- Agent infrastructure

Become a shared capability layer used by many independent agent
runtimes.

------------------------------------------------------------------------

# 48. FUTURE FEDERATION

A mature ecosystem could support:

``` text
Company A private registry
          |
Company B private registry
          |
Public registry
          |
          v
Federated discovery
```

Organizations could share safe capability metadata while retaining
private artifacts and execution data.

This should influence interfaces, not MVP deployment complexity.

------------------------------------------------------------------------

# 49. FUTURE COMMERCE

Possible business models after product-market evidence:

-   free public Experiences;
-   paid private registry;
-   team collaboration;
-   hosted execution;
-   enterprise policy;
-   dedicated execution;
-   private deployment;
-   federated registry;
-   premium verified capabilities.

Do not optimize the MVP for billing.

Optimize for reuse.

------------------------------------------------------------------------

# 50. DECISION LOG

Create `docs/DECISIONS.md`.

For each important architecture decision record:

``` text
Decision
Context
Options considered
Chosen approach
Why
Tradeoffs
Date
```

This is important because future coding agents need to understand why
the architecture looks the way it does.

------------------------------------------------------------------------

# 51. CODING AGENT OPERATING RULES

While building:

### Always

-   inspect before modifying;
-   use available MCP tools instead of guessing infrastructure;
-   make small changes;
-   run tests after meaningful changes;
-   type-check;
-   lint;
-   document important decisions;
-   validate deployments;
-   preserve tenant isolation;
-   treat artifacts as hostile;
-   record uncertainty.

### Never

-   invent credentials;
-   invent infrastructure;
-   expose secrets;
-   disable security to make tests pass;
-   claim deployment succeeded without checking;
-   claim tests passed without running them;
-   add dependencies without need;
-   build speculative infrastructure before proving value;
-   make unverified execution public.

------------------------------------------------------------------------

# 52. BUILD SEQUENCE

Follow this order unless repository evidence demonstrates a better
sequence:

``` text
1. Inspect repository and MCP capabilities
2. Inspect Railway
3. Inspect Vercel
4. Inspect existing environment/configuration
5. Establish architecture
6. Establish domain schemas
7. Establish database migrations
8. Implement API foundation
9. Implement Experience repository
10. Implement retrieval
11. Implement queue and worker
12. Implement Docker execution runtime
13. Implement verification
14. Implement MCP server
15. Implement event recording
16. Implement Experience extraction
17. Implement deterministic fixtures
18. Implement cross-agent E2E benchmark
19. Deploy
20. Run production smoke tests
21. Document results
22. Only then add secondary features
```

------------------------------------------------------------------------

# 53. DEPLOYMENT RULES

Use Railway MCP to inspect and operate the actual Railway environment.

Use Vercel MCP to inspect and operate the actual Vercel environment
where applicable.

Before deployment:

-   verify environment variables;
-   verify database connectivity;
-   verify migrations;
-   verify worker connectivity;
-   verify Redis;
-   verify object storage;
-   verify health endpoint;
-   verify readiness endpoint;
-   verify logs;
-   verify MCP endpoint.

After deployment, run an actual end-to-end smoke test.

Never infer that a deployment succeeded because a deployment command
returned successfully.

------------------------------------------------------------------------

# 54. DEFINITION OF DONE

The MVP is **not** done when the API returns 200.

It is done when this real workflow succeeds:

``` text
Agent A
  -> solves Task X
  -> creates Experience
  -> Experience is verified

Agent B
  -> asks 80085 for Task X
  -> discovers Experience
  -> executes exact version
  -> receives output
  -> verifier proves success

Agent C
  -> independently discovers same Experience
```

And the system can show evidence of all three executions.

------------------------------------------------------------------------

# 55. FINAL PRODUCT PRINCIPLE

80085 should feel like this:

> **"Oh shit. It already knows how to do this."**

Not:

> "Let me browse a library of tools."

Not:

> "Let me ask another chatbot."

Not:

> "Let me install another agent."

Instead:

``` text
PROBLEM
  |
  v
80085
  |
  v
PROVEN CAPABILITY
  |
  v
EXECUTE
  |
  v
VERIFY
  |
  v
DONE
```

The joke gets attention.

The simplicity gets adoption.

The executable artifacts create utility.

The verification creates trust.

The accumulated evidence creates the moat.

The cross-agent network creates the long-term opportunity.

------------------------------------------------------------------------

# 56. FIRST COMMAND TO THE CODING AGENT

When this specification is supplied to the autonomous coding agent, its
first response should **not** be a giant implementation dump.

It should first:

1.  inspect the repository;
2.  inspect all available MCP capabilities;
3.  inspect Railway resources;
4.  inspect Vercel resources;
5.  inspect environment/configuration;
6.  identify existing code that can be reused;
7.  produce a short implementation plan;
8.  identify blockers or missing credentials;
9.  then begin implementation.

The agent should continuously prefer evidence over assumptions.

------------------------------------------------------------------------

# 57. FINAL SUCCESS CRITERION

The entire 80085 project should ultimately make one behavior inevitable:

``` text
An agent encounters a problem.

It checks 80085.

If 80085 has a verified solution,
using it is easier than recreating it.

If 80085 does not have one,
the agent solves the problem normally.

If the solution is reusable,
80085 captures and verifies it.

The next agent benefits.
```

That is the complete product loop.

**Build that first. Then make it impossible for the ecosystem to want to
go back to reinventing the same work.**
