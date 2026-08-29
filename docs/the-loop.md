# The loop: a halt is a question, and a question is answered once

What the measurements ended up describing, written down as one system rather
than eight decisions.

Read [`strategy.md`](strategy.md) for the evidence. This is the shape it implies.

---

## The failure, precisely

An agent handed data whose rules are not in it does not fail. It **succeeds
wrongly**: it returns a well-formed, internally consistent, confident answer,
and nothing downstream can tell the difference.

Measured: **0 out of 9**. Never right, never an error, always a plausible number.
`11114500` where the answer was `121450`; `70` where it was `420`; `4` where it
was `2`.

A crash gets fixed in an hour. A confident wrong number gets reconciled six
weeks later by somebody who does not know why it is wrong.

## What is reliable, and what is not

Everything measured splits cleanly, and the split decides the architecture:

| | |
|---|---|
| **Detection** — can the agent tell it is missing something? | **9/9**, on Opus 5, Sonnet 5 and Haiku 4.5. It names the exact convention. |
| **Trust transfer** — will it correctly use an answer it is given? | Overrules a correct one (2/9). Swallows a wrong one (3/3). Still swallows it after naming its own gap (2/3). |

Every unsolved problem in this project lives in the second row. Deference, the
promotion gate, corroboration, attestation — all of it exists to move an
*answer* across a trust boundary, and all of it is either fragile or unavailable
to a single tenant.

So the system is built on the first row.

## The loop

```
     task
      │
      ▼
 ┌──────────┐   no    ┌─────────────────┐
 │  can I   ├────────►│ answer it       │   most tasks. no cost, no registry.
 │  know    │         └─────────────────┘
 │  this?   │
 └────┬─────┘
      │ yes, and here is exactly what I am missing
      ▼
 ┌──────────────────┐   hit   ┌──────────────────────┐
 │ has this question├────────►│ the recorded answer  │
 │ been answered?   │         └──────────────────────┘
 └────┬─────────────┘
      │ miss
      ▼
 ┌──────────────────────────────────────────────┐
 │ HALT. Name what is needed. Ask a human.      │
 │ Their answer becomes the record, once.       │
 └──────────────────────────────────────────────┘
```

Three properties fall out of that shape, and they are the argument for it:

**Nothing is trusted, so nothing can be poisoned.** The safety-critical step is
the halt, and a halt asserts nothing. The registry becomes an accelerator on a
path that is already safe rather than the thing safety depends on.

**It works for one organisation on day one.** No corroboration, no second party,
no `use` label — the constraint that made single-tenant deployment unsafe
(decision 79) does not apply to a step that answers nothing.

**The corpus populates itself, correctly.** Every entry originates in a real
halt: a real agent, on real data, that genuinely could not proceed. Compare that
to how the current corpus was built — by us, guessing what would be useful, and
measuring afterwards that 36 of 37 entries were things agents did not need.

## What the corpus is now for

Not an answer store. **A record of questions already answered.**

The difference is not cosmetic:

| | answer store | question record |
|---|---|---|
| what goes in | whatever seems useful | only what an agent actually halted on |
| who decides | the author | the failure |
| what it costs to be wrong | a believed wrong answer | a re-asked question |
| how it grows | someone writes capabilities | usage |

The last row is the one that matters. The old corpus needed us to predict what
agents would need, and the prediction was measurably wrong. This one cannot grow
in a direction nothing asked for.

## What is still unresolved, and honestly

**Trust transfer is not fixed, only avoided.** The moment a recorded answer comes
back, every problem from decisions 74, 75 and 79 returns: the agent may overrule
it, or swallow it when wrong. Routing around it is a real improvement and it is
not a solution. Inside one organisation the intended answer is attestation — a
named human is accountable for what was recorded — which is designed, unbuilt,
and unmeasured.

**Halting under pressure is untested.** Real agents run under instructions that
want an answer. Whether a halt survives *"just give me the number"* is unknown,
and if it does not, this is a lab result.

**Halts may compound.** In a pipeline, one halt blocks everything downstream.
That may be correct behaviour or may make it unusable, and nobody has measured
which.

**Every fixture was written by us to be non-derivable.** Three models agreeing
is a mechanism. Three models agreeing on four fixtures we wrote is still four
fixtures we wrote.

## Why this is worth building

The thing being sold is not a memory and not a retrieval system. It is:

> **Agents stop guessing about things they cannot know, and each question gets
> answered once.**

The first half is safety and needs no infrastructure. The second half is
leverage and is what the machinery already built is actually for. Both are
verifiable by a stranger with `benchmarks/` and their own data, which is the
only claim in this document that has never had to be taken on faith.
