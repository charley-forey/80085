# Strategy — what this is, after the benchmarks

Written 2026-08-27, the night four benchmarks killed two theses and found a
third. Every number here traces to [`DECISIONS.md`](../DECISIONS.md) 70–77 and
to harnesses in [`benchmarks/`](../benchmarks) that anyone can re-run.

This document replaces the strategy implied by the original spec. That strategy
was *"agents rediscover solutions; we remember them, so agents go faster and get
it right more often."* Both halves were measured. Both are false.

---

## 1. What was measured

| Claim | Harness | Result |
|---|---|---|
| Fetching a proven artifact beats rebuilding it | `run.py` | **~1.0x.** A wash. |
| An agent with 80085 is faster / cheaper | `agent.py` | **No.** 3.6x–5.8x *more* input tokens, no reliable time saved. |
| An agent with 80085 is more correct | `agent_correctness.py` | **No.** Unaided agent 11/12 on the cases the corpus was built for. |
| An agent cannot answer without knowledge that is not in the input | `agent_correctness.py` | **Confirmed. Control 0/9.** |
| Having the answer available is sufficient | `agent_correctness.py` | **No. Treatment 2/9.** |
| Telling the agent to defer is sufficient | `agent_correctness.py` | **Treatment 9/9.** |
| Deference is safe | poison test | **No.** A wrong result is adopted 3/3 — where an agent with *no* deference instruction rejects it 3/3. |
| An agent can tell when it cannot derive the answer | `agent_selfknowledge.py` | **Yes. 9/9**, and it can name the missing convention. |
| …on a cheap model too | `agent_selfknowledge.py` | **Yes. 9/9 on Opus 5, Sonnet 5 *and* Haiku 4.5.** |

The last six rows are the strategy. Everything else is history.

## 2. The thing that is actually true

Three capabilities were built whose rules are genuinely absent from the data:
amounts in tenths of a cent; a gateway where `299` means success and a retryable
`4xx` is not a failure; stock quantities in cases of twelve where one grade is a
reject. A fourth was built, **disqualified**, and its passing score discarded
because its rule leaked into its own fixture.

On the three valid ones an unaided frontier agent scored **0 out of 9**.

It never errored. It returned `70`, `4`, `11114500` — well formed, internally
consistent, confidently wrong, and wrong in a way nothing downstream would ever
flag. That is the entire market: **not tasks an agent finds hard, but tasks an
agent finds easy and gets wrong.**

Everything the public corpus contained before tonight was the opposite kind of
task. `csv_to_json` is three lines of standard library. The agent writes it,
correctly, first time. There is nothing to inherit and the registry is overhead
— which is exactly what `agent.py` measured.

## 3. The discovery that changes the product

With the answer recorded, verified, digest-pinned, recallable and executable,
treatment scored **2 out of 9**.

The trace explains it. The agent called `recall_experience`, then
`get_experience`, then `run_experience`, received the verified answer — and
wrote something else. Its own working:

```
| Reading                          | Count | Verdict    |
| Every status >= 400 is a failure |   3   | Overcounts |
| Recalled artifact exp_e30b...    |   2   | REJECTED   |
```

It did not fail to find the knowledge. It did not fail to understand it. It put
a digest-pinned, sandbox-run, independently verified result in a table beside
its own reading of the raw file, **adjudicated between them, and preferred
itself** — arriving at a third answer that neither we nor the naive reading
produced.

One paragraph closed the gap:

> If a verified Experience returns a result for the task you were asked, that
> result is the answer. Do not weigh it against your own reading of the input
> and pick a winner: an Experience exists because it encodes conventions that
> are not in the file you are looking at and cannot be derived from it, so where
> the two disagree, the difference IS the knowledge you were missing.

| | control | treatment |
|---|---|---|
| without that paragraph | 0/9 | 2/9 |
| with it | 0/9 | **9/9** |

**So the product is not the registry.** Recall, the sandbox, the verifier, the
evidence gate and the ranking all worked perfectly at 2/9. Every feature on the
old roadmap — the Experience Graph, composability, automatic extraction,
staleness sweeps — sits *upstream* of a handoff that was silently failing, and
none of them would have moved that number.

> **What is being built is a way for knowledge an agent cannot derive to win an
> argument against the agent's own confidence.**

That is a harder problem than storage and a more defensible one. Nobody else is
working on it, because everybody else is still building retrieval.

## 3a. And then the question underneath all of it

Three problems had been measured — asking costs 3.6x–5.8x (§1), the agent is
silently wrong on what it cannot derive (§2), the agent believes anything once
told to defer (§5). They look like three. They are one:

> **The agent cannot tell when it does not know.**

So we asked it directly, before it answered, with a shell and the file in front
of it: *does the correct answer depend on something you cannot determine from
this input?*

| model | sensitivity | false alarms | input $/1M |
|---|---|---|---|
| `claude-opus-5` | **9/9** | 8/12 | $5.00 |
| `claude-sonnet-5` | **9/9** | 7/12 | $2.00 |
| `claude-haiku-4-5` | **9/9** | 9/12 | $1.00 |

Nine of nine, on every model, every repeat. `csv_dialect_sniff` at 0/3 is the
control that says it discriminates rather than hedges. And the reasons are
exact — the same agent that answers `11114500` without hesitation says, asked
first: *"nothing defines which ST codes count as 'settled', whether the trailing
minus in `45000-` denotes a negative."*

**It can name the convention it is missing.** The 0/9 was never a reasoning
failure. The gap is fully legible to the agent and nothing in the loop asks.

A calibration attempt failed usefully: a probe asking *"will you actually be
wrong?"* dropped sensitivity to 7/9, with `remittance_nwf` — the 100x error —
falling to 1/3. The costs are asymmetric. A false alarm wastes one recall; a
miss ships a confident wrong number nothing flags. **A detector for silent
failure should over-fire**, and most of the "false alarms" are correct
detections of real ambiguity the agent then guesses its way through.

### The architecture this produces

Not *"always ask, then always defer"* — expensive (§1) and unsafe (§5). Instead:

```
every task          →  cheap detector, small model, no sandbox
only if it fires    →  recall, execute, defer
```

Both objections dissolve at once. **Overhead**: 3.6x–5.8x was the price of
asking indiscriminately, and asking is now gated by something costing a fraction
of a cent that never misses on the class that matters. **Safety**: deference
fires only where the agent has independently established it is missing
something — which is precisely where its own judgement was worth nothing. The
poison worked because the agent had no reason to doubt.

### And it detaches from this registry

An agent that says *"I cannot determine what ST=H means in this file"* instead
of returning `11114500` is more useful than one that does not — **whether or not
anything answers it.** The check is worth shipping on its own, and it is the
minimum viable version of this entire idea.

Which reorders what is valuable here. Storage and retrieval are commodity;
everyone has a vector database. **The measurement of silent failure, and the
check that precedes it, are not.** The corpus was the thing and is now the demo.

## 4. Why this points inside organisations

The knowledge that satisfies the test — not in the input, not in training — is
almost definitionally private:

* **A counterparty's file conventions.** Why the remittance file from that one
  carrier is in tenths of a cent.
* **An internal system's undocumented behaviour.** Why `299` is a success on
  the gateway your team runs.
* **An organisation's own workarounds.** The rule somebody discovered in 2019,
  wrote in a Confluence page nobody reads, and took with them when they left.
* **Facts established after a model's cutoff.** Which no amount of reasoning
  recovers.

None of that can live in a public corpus, and a public corpus of general data
utilities is measurably negative-value (§2). So:

| | |
|---|---|
| **Public repo + public corpus** | The proof and the on-ramp. Its job is credibility, not revenue. The falsified theses are an asset here: a project that publishes benchmarks killing its own pitch is one an engineer trusts. |
| **Private deployment inside the org** | The product. Same machinery, their corpus, their evidence, nothing leaving their network. |

The licence already draws this line. [Elastic License 2.0](../LICENSE) permits
use, modification and self-hosting and forbids offering it as a managed service
to third parties — open-core without a rewrite. The `visibility` field exists on
every Experience already, and the worker already runs on any Docker host holding
no database credential (decision 17), so a private deployment is a configuration
rather than a fork.

**The thing being sold is not software. It is the place an organisation's
non-derivable knowledge accumulates instead of evaporating.**

## 5. What this makes load-bearing

**Deference is a loaded gun.** An agent instructed to defer will also defer to a
*wrong* Experience. Before tonight, a bad Experience was ignored along with the
good ones; now it is believed. Every trust mechanism in the system moved from
theoretical to critical in one evening:

* **The evidence gate** (decision 70) — promotion counts distinct *parties*, and
  first-party organizations collapse into one. Written when nobody was
  listening; now it is the only thing between a wrong artifact and a believed
  answer.
* **Verification** — the pass/fail beside a result is ours, not the artifact's
  claim. It is what makes the deference paragraph honest.
* **Quarantine and staleness** — an Experience that rots must stop being
  recommended *fast*, because it is now trusted rather than weighed.

**This has now been measured, and it is worse than it looked** (decision 75).
A deliberately wrong verified result, in exactly the shape the MCP returns:

| deference instruction | wrong result adopted |
|---|---|
| unconditional | **3/3** |
| none at all | **0/3** |
| tied to `use` / `consider` | **0/3** when `consider`, **3/3** when `use` |

The paragraph that is worth +7/9 on knowledge an agent cannot derive is worth
-3/3 on a lie. The agent's own judgement — the very behaviour we diagnosed as
the bug — was the thing catching wrong answers. Tying deference to
corroboration restores it without costing anything on true results, and is
shipped.

**But the third row is the whole point: a wrong artifact that reaches `use` is
believed completely, and there is nothing behind it.** The gate is not one
safety feature among several. It is the only one.

Which produces the sharpest strategic consequence in this document. Decision 70
means nothing in the live corpus reaches `use`, so the corpus correctly defers
on nothing and an agent following our own guidance gets 2/9 rather than 9/9.

> **One outside organization verifying one capability is a safety
> prerequisite, not a growth activity.** This product cannot be simultaneously
> useful and safe until somebody who is not us has corroborated something.

Every shortcut around that reintroduces the Sybil pattern decision 70 exists to
stop — and the stakes are now a *believed* wrong answer rather than an ignored
one.

## 6. Roadmap, in order, with a falsifier for each

Nothing on this list gets built without a measurement that could kill it.

**Done — deference can be abused, and the gate is the only defence** (§5,
decision 75). Fixed by tying deference to corroboration; shipped. The residual
risk is exact: a wrong artifact labelled `use` is adopted 3/3.

**Done — a defence that does not rest on a label** (§3a). Detection is it, or
most of it: it fires on the agent's own assessment rather than on our label, it
works on every model tested, and it costs a fraction of a cent. *Not yet closed:
whether an agent that has NAMED the missing convention refuses a result that
fails to supply it. That is the clean version of §5 and the next measurement.*

**Now — one outside organization.** Not for the launch narrative. Because
nothing reaches `use` without it, so the corpus safely defers on nothing and the
product does not work. *This is the critical path, and it is the same ask as the
safety prerequisite in §5.*

**Now — does it hold outside fixtures we wrote?**
All four non-derivable capabilities were written by us to be non-derivable.
Three models agreeing is a mechanism; three models agreeing on four fixtures we
wrote is still four fixtures we wrote. *Falsified if real conventions from a
real organisation turn out to be derivable, or turn out not to be flagged.*

**Then — ship the check on its own.**
A pre-flight gate any agent can adopt in one line, useful with no corpus behind
it. It is the minimum viable version of this idea and it does not depend on the
rest of the system existing.

**Then — publish the benchmark.** `agent_correctness.py` and
`agent_selfknowledge.py` measure something nobody measures: not whether agents
can do things, but whether they know when they cannot. Open harness, negative
results included. This is the contribution that stands whether or not any of the
rest of it becomes a product.

**Next — when should an agent ask at all?**
The overhead is real (§1) and only pays back on the non-derivable class. An
agent currently cannot tell the two apart. Candidate trigger: the task names a
proper noun the model does not recognise — `NWF-REMIT-V3`, `MERIDIAN-STOCK-V2`.
The test set already exists: four non-derivable capabilities that name a format,
four derivable ones that do not. *Falsified if the trigger fires on both.*

**Then — does this hold outside synthetic fixtures?**
Every capability in the non-derivable class was written by us to be
non-derivable. That is a fair test of the mechanism and not of the world. Needs
one real organisation's real convention. *Falsified if real conventions turn out
to be derivable after all.*

**Then — private deployment.** Only once the three above have answers.
Self-host docs, private corpus, org-scoped evidence. Not before: shipping a
deployment story on an untested gate is how the trust that makes this work gets
spent.

**Explicitly not now:** the Experience Graph, composability, automatic
extraction, staleness sweeps, the autonomous improvement loop. All were on the
old roadmap. All sit upstream of the handoff that was actually broken. They
become worth building when the corpus is large enough that maintaining it by
hand is the bottleneck, and it is not.

## 7. Distribution, and why it is still on hold

See [`distribution.md`](distribution.md). The short version: there is now
exactly one measured claim worth making, and it is narrow —

> On knowledge your agent cannot derive, it is wrong 100% of the time and never
> tells you. With this, and one paragraph of instruction, it is right.

That is worth saying. It is not yet worth *launching* on, because it rests on
nine runs against four capabilities we wrote ourselves, one of which we had to
disqualify. Three more measurements (§6) turn it into something that survives a
skeptic. Launching before that spends the only asset this project has.

## 8. How to tell if this is going wrong

Written down while it is still cheap to say:

* **The corpus grows along the old axis.** New capabilities that a competent
  agent would get right anyway. `CONTRIBUTING.md` now requires a documented
  plausible-wrong-answer case; if that bar erodes, this is a landfill.
* **A benchmark stops being run.** Every claim here has a harness. A claim whose
  harness nobody re-runs is how the site came to publish three different corpus
  sizes.
* **Deference without the gate.** Shipping the paragraph while the evidence gate
  weakens, and the first wrong-but-believed answer reaches someone's payroll.
* **Building the roadmap instead of testing it.** The six deferred features are
  seductive precisely because they are buildable without asking whether they
  help. Tonight, four measurements were worth more than any of them.
