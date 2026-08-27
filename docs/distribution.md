# Distribution — how anyone finds out this exists

Written after Phase A and B, which is the only order in which it is honest.
Phase A built the harness that can prove the claim; Phase B made outside
evidence physically possible. This is what to do with them.

Read [`DECISIONS.md`](../DECISIONS.md) 70 first. It changes the pitch: the
corpus recommends `consider`, not `use`, and it will keep saying `consider`
until somebody who is not us runs something. That is not a caveat to hide. It
is the most persuasive thing the project has.

---

## The one asset

Every registry, list and launch below is a variation on the same sentence:

> Your agent will read that remittance file, sum the column, and tell you
> $111,145.00 with complete confidence. The answer is $1,214.50. It will not
> crash, it will not hedge, and nothing downstream will ever flag it.
>
> Three rules decide that number and **none of them is in the file.** No amount
> of reasoning recovers them. We measured it: unaided, an agent gets this class
> of question wrong **every single time**.

Nobody is short of AI tools. Everybody is short of AI tools that say what they
do not know. That is the wedge, and it is why the launch order is proof first
and reach second — reach spends credibility, and there is only one first
impression per channel.

**Two pitches have been measured and both are dead.** Recorded here so nobody
reaches for them again:

| Pitch | Benchmark | Verdict |
|---|---|---|
| *"The same answer, faster."* | `agent.py` | **No.** 3.6x–5.8x more input tokens, no reliable speed gain (decision 71). |
| *"An answer the agent would have gotten wrong."* | `agent_correctness.py` | **No.** Control scored 11/12 unaided (decision 72). |
| *"An answer the agent **cannot derive**."* | `agent_correctness.py` | **Yes — control 0/9** (decisions 73–74). The one that lived. |

Anyone who benchmarks this finds both in a morning. Better they find we
published them.

**There is now exactly one measured claim, and it is narrow:**

> On knowledge your agent cannot derive — a counterparty's file conventions, an
> internal system's undocumented behaviour — it is wrong **100% of the time**
> and never tells you. Control scored 0/9. With this registry, and one paragraph
> of instruction, 9/9.

The full argument is in [`strategy.md`](strategy.md). The short version: value
exists only for knowledge that is not in the input and not in training, and even
then only when the agent is told to defer — because with the answer in hand it
scored 2/9, having tabulated our verified result against its own reading and
preferred itself.

**C1 and C3 stay on hold, and that is the correct call rather than a delay.**
The claim above rests on nine runs against four capabilities we wrote ourselves,
one of which we had to disqualify for leaking its own rule. Three measurements
turn that into something that survives a skeptic:

1. Can deference be abused? Record a wrong Experience, see if it is believed.
2. When should an agent ask at all? The overhead is real and only pays back on
   the non-derivable class; nothing currently tells an agent which it is in.
3. Does this hold outside fixtures we wrote to prove it?

Launching before those spends the only asset this project has. The install
command was never the problem; the sentence above it was.

## Sequence

### C1 — Be where agent developers already are

The install is already the strongest asset in the project:

```bash
npx @80085-ai/cli init
```

No signup, no email, no dashboard, no browser. It mints a key, writes the MCP
config for Claude Code, Cursor, Windsurf and friends, and keeps the key in
`~/.80085/key` so a reinstall reuses it. Lead with that line everywhere; it
does more work than any paragraph.

| Where | What it needs | Why it matters |
|---|---|---|
| MCP server directories | A description and the one-line install | Where agent developers browse for capability, not for products |
| Claude Code plugin marketplace | A plugin manifest wrapping the same MCP endpoint | Highest-intent audience: people already extending an agent |
| `awesome-mcp` style lists | A pull request | Durable, indexed, and read long after a launch day |
| Cursor / Windsurf directories | Same config the CLI already writes | The config is generated; publishing it costs nothing |

`llms.txt` is already served, which means the *agents* can read the pitch
without a human in the loop. That is the distribution channel most projects do
not have and this one built first.

**Do not** buy attention for this. An agent registry with no third-party
evidence and paid traffic is a worse product than the same registry found by
someone who went looking.

### C2 — Recruit 3–5 design partners

**This is the gating step, not a parallel nice-to-have.** Until an outsider's
verified run exists, the front page says `consider` on every capability, and
C3's audience will check.

The ask is real work — attaching a worker means a Linux host with Docker,
`br_netfilter`, `CAP_NET_ADMIN` and x86 — so it has to be worth their while.
What a partner gets:

* A shared corpus their agents can recall from, private to them if they want it
* Their runs are the evidence that promotes a capability, and it is visible
* Direct influence over which capabilities get built next

Who to ask, in order of how little persuasion they need:

1. Anyone already running an agent fleet against repetitive, verifiable tasks
   — conversion, extraction, validation. The corpus is already aimed at them.
2. Teams who have built an internal "prompt library" and found it rots. They
   have felt the problem and named it something else.
3. Agent framework and harness authors. They do not need the corpus; they need
   a memory layer to point at, and one line of MCP config is the whole
   integration.

Ask for one thing: **run one capability and let the evidence count.** Not a
migration, not a commitment. The first outsider run is worth more than the next
thirty capabilities.

### C3 — One Show HN, carried by the negative results

There is exactly one first post. It goes out after A and B, and it leads with
what the project got wrong:

* `run.py` measures ~1.0x, and here is why that is the honest floor
* `agent.py` measures the real claim, and here is that number
* We defeated our own trust gate, found it by reading our own API against our
  own README, and fixed the gate rather than the README

An audience that has seen a hundred AI launches has never seen one open with
its own benchmark coming out flat. The `correctness.py` table — four cases
where the naive implementation returns a plausible wrong answer rather than
crashing — is the single most linkable artifact in the repository.

The name will do its own work. Let it; do not explain it twice.

### C4 — Money, deliberately not yet

Adoption is the goal, and revenue follows adoption or it does not deserve to.
Nothing below gets built before someone asks for it by name:

* **Private team corpora.** A company's own shared brain, same machinery,
  their evidence only. This is the product people will pay for, and it is
  mostly a visibility flag that already exists.
* **Metered hosted execution.** Workers cost money; running them for other
  people is the obvious meter. Note that the sandbox design deliberately
  refuses a managed container platform, so this is real infrastructure, not a
  billing toggle.
* **Self-host licensing.** The Elastic License already positions for it.

Building any of this now would trade the only thing the project has — a
believable evidence gate — for a revenue line with no customers behind it.

---

## Enterprise-grade — the honest list, deferred

Every one of these is a genuine requirement for a paying enterprise, and every
one is wasted work before a single outside organization has run anything:

SSO and real accounts (today the key *is* the account, deliberately — it is
why onboarding has no friction), audit log, per-organization data residency, a
SOC 2 path, worker autoscaling, an SLA.

Revisit when a design partner asks by name. Not before, and not because a
competitor's pricing page lists them.

---

## What would make this stop being worth using

Worth writing down while it is still cheap to say:

* **The corpus fills with capabilities nobody recalls.** Growth measured in
  entries rather than in recall hits is a corpus becoming a landfill.
  `/v1/admin/recall-misses` already records what agents asked for and did not
  find; that list, not the manifest, is the roadmap.
* **Evidence stops meaning anything.** Either by another gate failure, or by
  quarantine not keeping up with rot. The gate is the product.
* **The worker becomes the bottleneck** and executions queue for hours, which
  is now visible in `/v1/ready` as `workers.last_lease_age_seconds` rather
  than inferable only from a depth.
