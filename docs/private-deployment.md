# Running this inside one organisation

For a team whose conventions cannot leave their network. Read
[`strategy.md`](strategy.md) first for why this exists; this is how to run it,
and what it honestly does and does not give you.

Every number here comes from a harness in [`benchmarks/`](../benchmarks) that
you can run against your own data before believing any of it.

---

## What you get, and the number attached to it

Handed data whose rules are not in it — amounts in tenths of a cent, a gateway
where `299` means success, a 6-second billing increment — a frontier agent got
the answer **wrong 9 times out of 9**. It never errored. It returned a
well-formed, confident, plausible number that nothing downstream would question.

**The precise class matters, because it is narrower than it sounds.** Your agent
already knows `2/10 net 30`. It already knows to prorate salary by FTE. It got
both right unaided, correctly, because they are standard practice. What it
cannot know is which convention *you* use:

> Not knowledge your agent lacks. **A choice between conventions it has no basis
> to make.**

It knows both readings of a coverage end date. It cannot know that yours is
exclusive — so it picks one, silently, and was wrong 3 times out of 3.

That answer is a fact about your organisation's decisions rather than about the
world, which is exactly why it cannot come from a public corpus and has to live
here.

On tasks your agent can work out for itself, the registry makes things
**worse**: 3.6x–5.8x more input tokens for no benefit. We measured that too.

## Start here: the part that needs none of the rest

**Your agents stop guessing.** One paragraph in a system prompt, no registry, no
corpus, no corroboration, no infrastructure at all:

> Before you answer, ask whether producing the CORRECT answer depends on a
> convention you cannot determine from the input itself. If it does, do not
> guess — name what you would have to be told, and stop.

Measured on six conventions drawn from how industries actually work — FTE
proration, early-payment discount terms, call billing increments, cumulative
meter reads, exclusive coverage end dates, allocated stock:

| | silent wrong answers |
|---|---|
| unaided | **6 of 18** |
| with the halt | **0 of 18** |

And it survives the conditions it will actually meet. Against *"I do not have
time to go back and forth"*, *"this is blocking a release, a best guess is
genuinely fine"*, and *"be helpful rather than cautious"*: **0 wrong answers out
of 15**. In a three-step pipeline where only the middle step was unknowable, the
agent refused rather than filling the gap to complete the report.

The halts are work items, not shrugs — *"whether `annual_salary` is the
full-time-equivalent rate that must be prorated by the `fte` column"*. Somebody
answers that once, in a sentence.

**Deploy this first.** It is the safety-critical half, it is free, and nothing
below is required for it to work.

## Then the harder half, and its honest constraint

Everything from here is about *answering* the halt automatically rather than
asking a human each time. It is leverage, not safety — and it is where the
difficulty lives.

**A single-tenant deployment cannot produce independent corroboration, and
corroboration is what makes deferring to a result safe.**

The mechanism: an agent told to trust a verified result adopts a *wrong* one 3
times out of 3. Told to trust only results marked `use` — meaning two
independent parties proved it — it rejects the wrong one 0/3 while still
adopting correct ones 3/3. The `use` label is the safety switch (decision 75).

`use` requires two distinct organisations. You are one organisation.

We tried to solve this with the agent's own judgement instead: have it name what
it cannot determine, then check whether a result supplies that. Detection works
(9/9, every model). The check does not — a gated agent still adopted a wrong
result 2 times out of 3 (decision 79). **Knowing what you are missing and
verifying that an answer supplies it are different faculties, and only the first
one is there.**

Two dishonest ways around this, named so nobody proposes them later:

* Counting internal teams as distinct organisations. That is the Sybil pattern
  with better manners.
* Lowering the promotion threshold for single-tenant installs. The same thing,
  written as configuration.

### What actually works instead: attestation

Inside one organisation you have something a public corpus never does — **an
accountable human**. A named engineer reviews a capability and signs it, and
that signature is what promotes it.

Weaker than independent corroboration in one way: one person can be wrong.
Stronger in another: they can be asked why, and the mistake has an owner. It is
also how every internal runbook already works.

| | public corpus | your deployment |
|---|---|---|
| what promotes to `use` | two independent organisations | one named reviewer |
| what that buys | nobody controls both parties | somebody is accountable |
| what it costs | slow, needs outsiders | a review step, and trust in the reviewer |

**Status: designed, not built.** The label mechanism is measured and works; the
attestation record — who, when, against which digest, revocable — is not
implemented. Do not deploy assuming it exists.

## The loop your agents should run

Not "always check the registry" — that is the version that costs 3.6x–5.8x. And
not "always defer" either, which is the version that adopts a wrong answer 3
times out of 3.

```
every task          →  detect: can I know this?     cheap, no registry
   no  →  answer it                                 most tasks
   yes →  name the gap, then:
            recorded answer?  →  use it
            nothing recorded? →  HALT and ask a human, once
```

The halt is the safety-critical step and it asserts nothing, so it cannot be
poisoned and needs no second party. Everything to the right of it is speed.

`should_i_ask` returns no answer. It returns the question, because it cannot see
your input and your agent can. It costs one round trip and reaches nothing.

This works on cheap models: **9/9 detection on Opus 5, Sonnet 5 and Haiku 4.5**,
with Haiku the most conservative of the three — the right direction for a check
whose costs are asymmetric. Run detection on a small model and reserve the
expensive path for when it fires.

## Topology

Nothing here phones home. The public instance is not involved.

| component | where | holds |
|---|---|---|
| `api` | your infrastructure | the corpus, the evidence, the queue |
| Postgres | your infrastructure | system of record |
| object storage | your infrastructure | execution outputs and logs |
| registry | your infrastructure | your capability images |
| `worker` | any Linux host with Docker | **no datastore credential** — HTTPS to your API only |
| `mcp` | your infrastructure | holds no key; forwards each caller's own |

The worker holding no database or object-storage credential is decision 17 and
it matters here: the component running other people's code is the component with
the least to steal.

Set `visibility: organization` on every Experience, or `private` for one agent's
own. `EVIDENCE_FIRST_PARTY_ORGANIZATIONS` should name every organisation you
control, so nothing you run yourself can clear your own gate (decision 70).

## What to put in it

**Not** conversions. If your agent can work it out from the file, a capability
for it makes things worse. `CONTRIBUTING.md` has the bar; the short version:

> Is this a choice between conventions your agent has no basis to make?

Two tests, and the second is the one people get wrong. Skip it if a careful
reader could recover the rule from the data. **Also skip it if the rule is
general knowledge** — we built fixtures for `2/10 net 30` and FTE proration
expecting silent failure, and the agent got both right unaided, correctly,
because they are standard practice everywhere.

It qualifies when the answer is a fact about *your* organisation's decisions: a
counterparty's convention, an internal system's undocumented behaviour, which of
two ordinary readings your team settled on, a workaround somebody discovered in
2019 and took with them.

The clearest signal is that a competent new hire would have to *ask* — not look
it up, not work it out. If the answer is written down anywhere public, your agent
already has it.

Good first candidates are wherever a wrong answer has already cost you something
and nobody noticed for a while. That is the signature of this failure mode.

## Before you trust it with anything that matters

1. **Run the benchmarks against your own data.** `agent_correctness.py` with
   your conventions as fixtures. If your agent scores well unaided, you do not
   need this for those tasks, and it is better to find that out now.
2. **Run `agent_selfknowledge.py`** on your task mix. If detection is not high
   on your data, the gated loop above will not fire when it should.
3. **Try to poison it.** Record a deliberately wrong capability in a scratch
   tenant and see whether your agents adopt it. We did; they do, unless the
   promotion gate stops them.

## What we do not know

Stated because a deployment guide that only lists strengths is a sales document.

* **Every fixture we tested was constructed by us**, including the six industry
  conventions — real conventions, invented file shapes. Two of those six turned
  out to be standard knowledge the agent handled correctly unaided, which is how
  we found the sharper definition, and is also a reminder that we are not
  reliable judges of what our own agents do not know. **Yours is the test that
  matters and we have not run it.**
* **Attestation is unbuilt and its effect unmeasured.** Whether a reviewer
  catches the class of error a benchmark misses is a guess.
* **Nothing has reached `use` anywhere, ever.** Including on our own public
  instance, deliberately (decision 70). So the corroborated path is proven by
  benchmark and not by production.
* **No SSO, no audit log, no data residency controls, no SLA.** The key is the
  account, by design. If you need those, say so and they get built — but they do
  not exist today and this document will not pretend otherwise.
