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

> Your agent will confidently tell you the last business day of December 2021
> was the 31st. It was the 30th. It will not crash, it will not flag it, and
> you will ship it. This registry remembers the edge cases somebody already
> paid to discover — and it will not call one proven until someone other than
> its author has proven it. Ours are not proven yet.

Nobody is short of AI tools. Everybody is short of AI tools that say what they
do not know. That is the wedge, and it is why the launch order is proof first
and reach second — reach spends credibility, and there is only one first
impression per channel.

**Do not pitch speed.** `agent.py` measured it and 80085 lost: on conversion
tasks it costs 3.6x–5.8x more input tokens than letting the agent write the
code. That is a real finding about where this belongs, not a flaw to hide, and
publishing it is what makes the correctness claim believable. Anyone who
benchmarks us will find it in a morning; better they find we published it.

The claim that survives contact with a benchmark is correctness, and it has the
useful property of *not eroding as models improve*: a better model closes the
speed gap and cannot deduce a fact about the 2021 US holiday calendar.

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
