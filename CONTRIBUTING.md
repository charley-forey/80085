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

The bar that actually holds is stricter, and it moved again once we stopped
inventing the conventions ourselves (decision 81). Ask:

> **Does this encode a choice between conventions, made by one organisation or
> one counterparty — rather than something an agent already knows?**

Not "knowledge the agent lacks". A *choice between conventions the agent has no
basis to make*. It knows both readings of a period end date; inclusive and
exclusive are both ordinary. What it cannot know is which one **your** company
uses, so it picks one silently and is wrong 3 times out of 3. The answer is a
fact about one organisation's decisions, not a fact about the world.

**Two worked counter-examples, because we got these wrong ourselves.** We built
`ap_early_payment` around `2/10 net 30` and `payroll_fte` around prorating
salary by FTE. Both rules were absent from the input, so both cleared the old
bar. Both are also standard trade and payroll practice, firmly in training, and
the unaided agent answered them correctly 3/3 — no capability required. Absent
from the file is not the same as unknowable. If a competent practitioner in that
industry would read your fixture and say "well obviously it means X", the agent
says it too, and your capability is overhead.

What did qualify, from the same batch: `telecom_billed_seconds` (which rounding
increment this carrier bills on), `policy_coverage_days` (whether this insurer's
end date is inclusive), `inventory_available` (whether allocated — or in-transit
— stock counts as available). Each is a local pick among options the agent knows
perfectly well. Unaided, silent wrong answers **6 of 18**; with the halt in
place, **0 of 18**.

The older worked examples still hold: `remittance_nwf` (amounts in tenths of a
cent), `apilog_zenith` (`299` is this gateway's success code), `sku_meridian`
(quantities in cases of twelve) — an unaided agent scored **0 out of 9** on
those, never right, never an error, always a plausible silent wrong answer
(decisions 73-74).

And one counter-example kept deliberately: `part_supersede_orbital` was
**disqualified** because its rule leaked into its own fixture, and an unaided
agent scored 3/3. A capability whose rule is recoverable from its own inputs
tests nothing. `ap_early_payment` and `payroll_fte` fail the same test from the
other direction — their rule is recoverable from the agent's training instead of
from the file.

So answer both questions in the pull request:

> **What does the obvious implementation return, and why does nobody notice?**
>
> **Which two conventions could this be, and why can no one outside this
> organisation tell which one is in force?**

If you cannot name the *other* convention it plausibly could have been, there is
no choice being encoded, and there is probably no capability either.

**One more thing, and it is the reason the bar is this high.** A recorded answer
is deferred to (decision 74), so a wrong Experience is not ignored — it is
believed. Note also what a capability now competes with: the halt. An agent that
detects the gap and refuses ships no wrong number at all, needs no corpus, and
is safe on day one (decision 80). A capability only earns its place by turning
that halt into an answer, which means being right.

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
