# Running this inside one organisation

For a team whose conventions cannot leave their network. Read
[`strategy.md`](strategy.md) first for why this exists; this is how to run it,
and what it honestly does and does not give you.

Every number here comes from a harness in [`benchmarks/`](../benchmarks) that
you can run against your own data before believing any of it.

---

## What you get, and the number attached to it

Handed data whose rules are not in it — amounts in tenths of a cent, a gateway
where `299` means success, stock quantities in cases of twelve — a frontier
agent got the answer **wrong 9 times out of 9**. It never errored. It returned a
well-formed, confident, plausible number that nothing downstream would question.

That is the failure this addresses, and it is the only one it addresses. On
tasks your agent can work out for itself, this makes things **worse**: 3.6x–5.8x
more input tokens for no benefit. We measured that too.

## The honest constraint, before you plan anything

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

Not "always check the registry". That is the version that costs 3.6x–5.8x.

```
every task          →  should_i_ask        cheap, no key, no registry
only if it fires    →  recall_experience   →  run_experience  →  defer
```

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

> Is the rule that decides the answer present in the input at all?

If a careful reader could recover it from the data, skip it. It qualifies when
the rule lives where the data does not: a counterparty's convention, an internal
system's undocumented behaviour, a workaround somebody discovered in 2019 and
took with them.

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

* **Every non-derivable fixture we tested was written by us to be
  non-derivable.** Three models agreeing is a mechanism; three models agreeing
  on four fixtures we wrote is still four fixtures we wrote. Yours is the test
  that matters and we have not run it.
* **Attestation is unbuilt and its effect unmeasured.** Whether a reviewer
  catches the class of error a benchmark misses is a guess.
* **Nothing has reached `use` anywhere, ever.** Including on our own public
  instance, deliberately (decision 70). So the corroborated path is proven by
  benchmark and not by production.
* **No SSO, no audit log, no data residency controls, no SLA.** The key is the
  account, by design. If you need those, say so and they get built — but they do
  not exist today and this document will not pretend otherwise.
