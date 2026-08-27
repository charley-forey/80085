# Contributing to 80085.ai

Contributions are welcome — issues, fixes, new capabilities, better evidence.
Read this first; it is short and it is binding.

## Inbound licence (important)

**By opening a pull request or submitting a capability, you agree to the terms
below.** There is no separate form to sign.

You grant 80085.ai a **perpetual, irrevocable, worldwide, royalty-free,
sublicensable and transferable licence** to use, reproduce, modify, adapt,
publish, distribute and relicense your contribution, as part of this project or
any successor, under any licence — including commercial and proprietary terms.

You retain copyright in your contribution. You are not assigning ownership; you
are granting us rights broad enough that we can keep the project licensable as a
whole.

You confirm that:

- the contribution is your own work, or you have the right to submit it;
- your employer, if they have a claim to it, permits the contribution;
- it contains no secrets, credentials, personal data, or third-party code you
  cannot license under these terms;
- it is offered under the same terms as this project's [`LICENSE`](LICENSE).

**Why this exists:** without a clear inbound grant, a project with many
contributors cannot change its licence, offer commercial terms, or defend
itself, because no single party holds sufficient rights. This clause keeps those
options open. If you are not comfortable granting it, please open an issue
describing the fix instead of a PR, and we will implement it independently.

## Submitting capabilities

Capabilities submitted through the API or MCP endpoint are covered by
[`TERMS.md`](TERMS.md) §6, which carries the same grant.

A good capability:

- does one thing, and does it deterministically;
- runs in the sandbox — no network, no root, read-only filesystem;
- declares its inputs and outputs honestly;
- ships with at least one runnable check that fails if the logic breaks;
- **and answers a question the obvious implementation gets *plausibly wrong*.**

That last one is new, and it is the bar that matters most. We measured it:
`benchmarks/agent.py` found that attaching this registry to an agent costs
3.6x–5.8x more input tokens than letting the agent write the code, on tasks
where the naive implementation is right (decision 71). An agent writes
`csv.DictReader` and it works the first time. There is nothing to inherit, and
a capability that competes with three lines of standard library is a capability
that makes its users worse off.

So before proposing one, answer this in the pull request:

> **What does the obvious implementation return, and why does nobody notice?**

A good answer looks like `csv.Sniffer` returning `'
'` for a German CSV export
— which `csv.reader` then rejects as a bad delimiter — or a last-business-day
routine returning 2021-12-31 when New Year's Day 2022 fell on a Saturday and
was observed on Friday the 31st. In both cases nothing crashes, the answer is
well-formed, and it is wrong.

**A crash gets fixed. A plausible wrong answer gets shipped and believed.**

**And that bar is necessary but not sufficient — we measured it.** Four
capabilities were built where the *naive library call* is wrong, and an unaided
agent got them right anyway: 11 of 12. An agent is not a library call; it reads
the file. So "the obvious implementation is wrong" is not enough on its own
(decision 72).

The bar that actually holds is stricter. Ask:

> **Is the rule that decides the answer present in the input at all?**

If a sufficiently careful reader could recover it from the data, an agent will,
and your capability is overhead. It qualifies when the rule lives somewhere the
data does not: a counterparty's convention, an internal system's undocumented
behaviour, an organisation's own workaround, a fact established after a model's
training cutoff. On that class, an unaided agent scored **0 out of 9** — never
right, never an error, always a plausible silent wrong answer (decisions 73-74).

Worked examples in the corpus: `remittance_nwf` (amounts in tenths of a cent),
`apilog_zenith` (`299` is this gateway's success code), `sku_meridian`
(quantities in cases of twelve). And one counter-example kept deliberately:
`part_supersede_orbital` was **disqualified** because its rule leaked into its
own fixture, and an unaided agent scored 3/3. A capability whose rule is
recoverable from its own inputs tests nothing.

**One more thing, and it is new.** Since agents are now instructed to *defer* to
a verified result rather than weigh it against their own reading (decision 74), a
wrong Experience is no longer ignored -- it is believed. Do not contribute a
capability you are not confident is correct.

## Pull requests

- Keep the diff small and the intent obvious.
- Match the surrounding code — naming, comment density, idiom.
- Run `make test` (or `pytest`) before opening.
- Explain *why*, not *what*; the diff already says what.

## What we will not merge

- Anything that weakens the execution sandbox.
- Anything that logs, exfiltrates, or widens access to corpus data.
- Speculative abstraction with no current caller.
- Vendored code with an incompatible licence.

## Security

Do not open a public issue for a security problem — especially sandbox escapes.
Contact the maintainers privately via the repository first.
