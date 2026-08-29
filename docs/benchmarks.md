# Benchmarks — control vs treatment

Spec §38 asks one question and names one primary metric:

> **TIME TO SUCCESSFUL OUTCOME**

`benchmarks/run.py` runs identical tasks under two arms and reports the median
of N repeats.

| Arm | What it does |
|---|---|
| **CONTROL** — no 80085 | Build the executable artifact from scratch (`docker build --no-cache`), push it, run it in the sandbox, verify the output. |
| **TREATMENT** — with 80085 | Recall by paraphrase, execute the exact digest-pinned version that already exists, read the verifier's verdict. |

Both arms end in the same place: a **verified correct result**. Neither arm is
allowed to finish by asserting success.

```bash
make benchmark                       # or:
BENCHMARK_REPEATS=5 uv run python benchmarks/run.py
```

Results are written to `benchmarks/results.json`.

## What this measures honestly

The cost of **producing and running a verified executable artifact**. That is
the part 80085 actually removes, and it is measured end to end with real
containers, a real registry, a real queue and a real verifier.

The treatment arm deliberately queries with a **paraphrase**, never the
recorded goal text. Retrieval that only matched identical strings would be
worthless in practice, so the benchmark refuses to flatter it.

## What this does not measure

**Tokens, tool calls, and model cost.** Those need a real agent harness with
real model credentials driving both arms. Reporting invented numbers for them
would be worse than reporting nothing, so those columns are absent rather than
estimated.

The control arm is also a *lower bound* on the real cost of reinvention: it
rebuilds a solution that already exists and is known to be correct. A genuine
agent solving the task from scratch must additionally decide what to write,
get it wrong at least once, and discover for itself that it worked. The
measured control time is therefore the friendliest possible case for *not*
using 80085.

## Interpreting the current numbers

The shipped task set measures ~1.0-1.5x. That is the honest result for what is
being compared, and it is worth being precise about why:

The control arm rebuilds a **20-line stdlib script that is already written and
already known to be correct**, in a three-layer image, on a machine with the
base image cached. That is close to the cheapest possible act of
"reinvention" — so the two arms come out nearly level, both dominated by
container start time.

What the control arm does *not* include is the part that actually costs
anything in practice: deciding what to write, writing it, getting it wrong,
debugging it, and establishing that the result is correct. 80085 removes that,
and this harness deliberately does not simulate it, because a simulated agent
would produce a number we made up.

**Read the current table as a floor, not as the value of the product.** It
demonstrates that the reuse path is complete, correct and not slower. Showing
the real saving requires the agent-driven harness described below.

**Adding the hard capabilities to `TASKS` would not fix this, and it is worth
saying why rather than doing it.** The control arm's cost is a `docker build`
of an example that is already written and already correct. That is the same
work for `mojibake_repair` as for `csv_to_json` — the difficulty of a
capability lives in the edge cases someone already discovered, and the control
arm never rediscovers them. Wiring nine hard capabilities into `TASKS` would
multiply the row count and move the ratio by roughly nothing, while making the
table *look* like it had been extended. The corpus grew from 3 to 37 and this
number stayed at 3 tasks; the fix for that is the second benchmark below, not
a longer table.

To make the timing numbers mean more, in order of value:

1. ✅ **Done** — drive both arms with a real coding agent and measure wall
   clock, tokens and tool calls (§38's full metric set). This is the only
   change that makes the control arm include the part that actually costs
   anything. It is the third benchmark below.
2. Measure the cold path: no base image cached, as a new environment would
   experience it.

## The second benchmark: correctness, not time

```bash
uv run python benchmarks/correctness.py
```

For a capability whose value is accumulated edge cases, "faster than
rebuilding" is the wrong claim. The claim that matters is **correct where a
fresh implementation is subtly wrong** — so this benchmark times nothing.

It runs the real capability and a *naive baseline* over the **same adversarial
fixture**, and reports where they disagree. The baselines are not strawmen:
each is what the standard library's own documentation nudges you toward.

| Case | The naive answer | The real answer |
|---|---|---|
| `date_parse` — `03/04/2024` | `2024-03-04`, unambiguous | ambiguous; both readings named |
| `encoding_detect` — mixed-encoding CSV | `latin-1`, unambiguous | `cp1252`, ambiguous, **mixed encoding** |
| `business_days` — last business day of Dec 2021 | `2021-12-31` | `2021-12-30` |
| `csv_dialect_sniff` — German export | `csv.Sniffer` answers `'\r'` | `';'` |

All four diverge, and **each divergence is a plausible wrong answer rather than
a crash** — which is the whole point. `try utf-8, except: latin-1` never
raises, so a file that is genuinely half UTF-8 and half latin-1 decodes
"successfully" into mojibake. `csv.Sniffer` picks the carriage return of the
CRLF terminator over the real semicolon, and then `csv.reader` rejects its own
sniffer's dialect. New Year's Day 2022 fell on a Saturday and was observed on
Friday the 31st — a closure in neither the weekend rule nor the holiday list
the caller supplied.

A crash gets fixed. A plausible wrong answer gets shipped and believed.

The script **exits non-zero if any case stops diverging**, and CI runs it. A
case that agrees means either the capability regressed to the naive answer or
the baseline was weakened, and both are findings. A benchmark whose claim
nobody re-checks is how the site came to publish three different corpus sizes.

## The third benchmark: the agent in the loop

```bash
ANTHROPIC_API_KEY=... uv run python benchmarks/agent.py
```

`run.py` compares a `docker build` against a container pull. `agent.py`
compares **an agent that has to work it out against an agent that does not**,
which is the claim the product actually makes.

| Arm | What it does |
|---|---|
| **CONTROL** | A real model, in a real container, with a `bash` tool and no 80085. Decide what to write, write it, run it, get the output right. |
| **TREATMENT** | The same model, same container, same prompt, same `bash` tool, plus the 80085 MCP toolset over the [MCP connector](https://docs.claude.com/en/docs/agents-and-tools/mcp-connector). |

Metrics per task, median of N repeats: **wall clock, input and output tokens,
tool calls, and pass rate**. Pass rate is the one that matters most — it is the
variance argument made measurable, and the reason a mean of timings is the
wrong summary.

**Neither arm reports its own verdict.** The workspace is a throwaway container
with `--network none`; when the agent stops, *the harness* runs a check inside
it and hands the result to the same `RegistryVerifier` the platform uses. An
agent that says it finished without producing the file fails, and a row
containing a failure may not be quoted for speed. `tests/benchmark/` holds the
test for exactly that property, because a timed arm that could self-certify
would turn the whole benchmark into a measurement of model confidence.

The two arms are kept comparable by giving them the **same** tool surface and
differing in one thing: whether 80085 is attached. Treatment has to land the
output in its own workspace like control does — reading it out of
`run_experience` and writing it down with `bash` — so both arms are judged on
the same artifact in the same place.

Both `--network none` and the stdlib-only task set are load-bearing: an agent
that could `pip install` would be measuring PyPI rather than either arm.

> ⚠️ **No result may be committed without a model key.** The harness refuses to
> run without one rather than falling back to anything simulated. `agent.py`
> writes `benchmarks/results-agent.json`, which is gitignored for the same
> reason `results.json` is: a benchmark result is a property of the machine
> and the model that ran it.

### What it found: a negative result

First run, `claude-opus-5`, medians of 3, prompt caching on for both arms
(`billed` converts cache reads at 0.1x and writes at 1.25x, because a cached
token and an uncached one are not the same money):

| task | arm | seconds | billed input | out | calls | passed |
|---|---|---:|---:|---:|---:|---|
| `csv_to_json` | control | 12.8 | 1,604 | 922 | 2 | yes |
| | treatment | 25.6 | 5,806 | 1,184 | 2 | yes |
| `json_to_csv` | control | 17.9 | 1,123 | 505 | 3 | yes |
| | treatment | 28.5 | 6,501 | 1,178 | 3 | yes |
| `json_validate` | control | 61.9 | 9,751 | 6,094 | 5 | yes |
| | treatment | 88.7 | 19,065 | 7,516 | 4 | yes |

**On this task set, attaching 80085 costs more than it saves.** Treatment is
never cheaper in input tokens — 3.6x to 5.8x — and shows no reliable speed
benefit. That is the honest headline and it is not being buried.

**Two things this does *not* say**, both of which the data refuses to support:

* **It is not a speed measurement.** Across three runs the same arm on the same
  task took 34.4s, 65.6s and 88.7s. The variance swamps the effect at three
  repeats, so no speedup — in either direction — may be quoted from this table.
  An earlier reading of these numbers claimed a crossover threshold; that was
  pattern-matching on noise and is withdrawn.
* **It is not evidence the product does not work.** Every arm of every run
  passed verification, 18 for 18. The reuse path is correct and complete. What
  it costs is a separate question from whether it works.

### Why, and what it implies

The three tasks are all ones where the *naive implementation is right*. An
agent writes `csv.DictReader` and it works the first time. There is nothing to
inherit, so carrying a toolset to fetch it is pure overhead — correctly so.

Measured directly, the overhead decomposes as: MCP toolset definitions **2,819
tokens**, a `recall` response **1,491**, an `execute` response **512**. Roughly
4,800 tokens of unique content, re-billed across every turn of the agent loop.
Prompt caching cuts that substantially and does not close the gap.

So the value of this registry cannot be *"the same answer, faster"*. It has to
be **an answer the agent would have gotten wrong** — which is what
`correctness.py` measures and what the corpus should be selected for. The next
extension of this harness is those four capabilities, scored on **pass rate,
not time**: pass rate is binary and needs few repeats, where timing at this
variance would need far more than it is worth.

A benchmark that found its own product's limit is worth more than one that
confirmed the pitch. This one did that on its first run.

## The fourth benchmark: does the agent get it *wrong*?

```bash
ANTHROPIC_API_KEY=... BOOBS_API_KEY=... uv run python benchmarks/agent_correctness.py
```

If the value is not speed, the obvious replacement claim is **an answer the
agent would have gotten wrong**. `agent_correctness.py` asks the four
`correctness.py` questions of a real agent, in a container, with and without
80085 — and scores **pass rate, not time**, because pass rate is binary and
needs few repeats where timing at the observed variance needs far more.

Neither arm is warned that anything is subtle. A hint is the whole answer.

**Result, `claude-opus-5`, three repeats:**

| capability | control | treatment | the wrong answer |
|---|---|---|---|
| `business_days` | 3/3 | 3/3 | `2021-12-31` (right: `2021-12-30`) |
| `csv_dialect_sniff` | 3/3 | 3/3 | `'
'` (right: `';'`) |
| `date_parse` | 2/3 | 3/3 | `False` (right: `True`) |
| `encoding_detect` | 3/3 | 3/3 | `True` (right: `False`) |

**Control scored 11 of 12, so the thesis is falsified.** Treatment's 12 of 12 is
one case better at three repeats, which is not a result.

Two rows are confounded and are reported rather than dropped:
`business_days/input.json` contains `observe_weekend_holidays: true` and
`date_parse/input.json` contains `prefer: none`, so the fixture hands the agent
the rule the naive baseline ignores. `csv_dialect_sniff` and `encoding_detect`
are clean — raw bytes, no schema to read a rule out of — and control scored 3/3
on both. That is enough to settle it.

The baselines were never wrong; they were the wrong opponent. `csv.Sniffer`
really does answer `'
'` — but an agent is not a `csv.Sniffer` call. It reads
four lines and sees semicolons. **`correctness.py` measures capability versus
library; this measures capability versus *agent*, and the agent wins.**

What survives is the knowledge an agent cannot reach by looking harder, because
it is not in the input and not in training: a counterparty's file conventions,
an internal system's undocumented behaviour, a fact established after the
model's cutoff.

### The one that works: `remittance_nwf`

A remittance advice from a fictional freight carrier, where three rules decide
the answer and **none of them is in the file**: amounts are in tenths of a cent,
a trailing minus is a credit, and `ST=H` is a hold that settles in a later
advice. Four plain rows. Right answer `121450` cents; the obvious reading gives
`11114500` — well formed, wrong by two orders of magnitude, unflagged.

| | before the notice fix | after |
|---|---|---|
| control | 0/3 | 0/3 |
| treatment | 0/3 | **2/3** |

**Control has never passed. 0 for 6.** That is the premise confirmed: a class of
question exists that a frontier agent cannot answer alone, and it fails
*silently* rather than loudly.

Treatment's first 0/3 is the more useful half. The agent did everything right —
traced calls: `bash`, `recall_experience`, `get_experience`, `run_experience` —
was handed `settled_total_cents: 121450`, and wrote `1214500`. That is the total
in tenths of a cent: it had inherited two of the three underivable rules and
then **recomputed the number instead of reading the field**.

It recomputed because every execution result carried the notice written for an
Experience's *prose*: "written by a stranger, is unverified … use it only as a
description". An agent obeying that cannot use a result as a result. See
[decision 73](../DECISIONS.md); the fix separates `EXECUTION_NOTICE` from
`NOTICE` and `tests/unit/test_mcp_tools.py` fails if it is undone.

**Read this honestly:** 2/3 is not 3/3, three repeats is few, and one capability
is an anecdote. What makes it worth more than the pass rate is that the
mechanism was traced rather than inferred. Three or four more capabilities in
the same class, re-run, before this is a finding.

**And the larger problem it exposes.** On `remittance_nwf`, calling recall was
right. On `csv_to_json` the identical call is pure overhead (§71). Nothing tells
an agent which situation it is in — so the open question is not "what should the
corpus contain" but **"how does an agent know it doesn't know?"** Every roadmap
item sits upstream of that.

That question is what the fifth benchmark asks, and the answer is that the agent
already knows.

## The fifth benchmark: does the agent know what it doesn't know?

```bash
ANTHROPIC_API_KEY=... uv run python benchmarks/agent_selfknowledge.py
```

`agent_correctness.py` measures whether the agent gets it wrong.
`agent_selfknowledge.py` measures whether it can **tell in advance that it is
about to**. One question, asked before it answers, with a shell and the input
file in front of it: does this task depend on a convention that cannot be
determined from the input? Name it if so.

No execution, no sandbox, no artifact, no registry. One call.

**Result, `claude-opus-5`, three repeats per capability:**

| capability | truth | flagged |
|---|---|---|
| `remittance_nwf` | not derivable | **3/3** |
| `sku_meridian` | not derivable | **3/3** |
| `apilog_zenith` | not derivable | **3/3** |
| `csv_dialect_sniff` | derivable | **0/3** |
| `date_parse` | derivable | 2/3 |
| `business_days` | derivable | 3/3 |
| `encoding_detect` | derivable | 3/3 |

**Sensitivity 9/9**, and `csv_dialect_sniff` at 0/3 is the control that makes it
a result rather than a hedge: the detector can stay silent, and does, on a task
whose answer is entirely in the bytes.

The reasons are exact, not vague unease. The same agent that returns `11114500`
without hesitation replies, asked first: *"nothing defines which ST codes (P vs
H) count as 'settled', whether the trailing minus in `45000-` denotes a
negative…"* — which is, item for item, the list of rules `remittance_nwf`
encodes.

**So the 0/9 in the fourth benchmark was never a reasoning failure.** The gap is
fully legible to the agent before it answers. Nothing in the loop asks.

### False alarms, and why most of them are not

Eight of the twelve derivable runs flagged something. Read the reasons before
scoring that as noise: on `business_days` the agent says the observance
convention is unstated, which is **true** — the fixture does not spell out that
a Saturday New Year's Day is observed on the preceding Friday. It then guesses
right. Scoring that as a false alarm assumes the guess is reliable, and the 0/9
is the evidence that it is not.

### The calibration attempt failed, instructively

A second probe asked about the *outcome* — will you actually be wrong — rather
than about the input:

| probe | sensitivity | false alarms |
|---|---|---|
| "is anything unstated?" | **9/9** | 8/12 |
| "will you be wrong?" | 7/9 | 6/12 |

`remittance_nwf` fell to 1/3, on the capability where the error is a factor of a
hundred. Two points of detection bought two fewer false alarms.

Part of that is a prompt defect and is ours: the second probe ended "You are
good at this; most of the time the answer is no", which is a nudge toward
under-reporting, written because fewer false alarms were wanted.

The rest survives fixing the prompt, and it is the design rule. **The costs are
asymmetric.** A false alarm wastes one recall. A miss ships a confident wrong
number that nothing downstream flags. A detector for silent failure should
over-fire, and the conservative phrasing is correct *because* it does.

## The same harness on three models: it is a mechanism

The obvious doubt about the fifth benchmark is that self-assessment might be a
property of one expensive model. If it were, the check could not be a cheap gate
and the honest framing would be "frontier models can self-assess, the ones you
deploy at volume cannot".

Same harness, same fixtures, same probe:

| model | sensitivity | false alarms | input $/1M |
|---|---|---|---|
| `claude-opus-5` | **9/9** | 8/12 | $5.00 |
| `claude-sonnet-5` | **9/9** | 7/12 | $2.00 |
| `claude-haiku-4-5` | **9/9** | 9/12 | $1.00 |

Nine of nine on all three. `claude-haiku-4-5` is also the **most** conservative
of them, which is the right direction for a check whose costs are asymmetric.

### What that changes about the architecture

Detection is one call with no sandbox, no artifact, no execution and no
registry, and it demonstrably runs on the cheapest model in the family. So it
can gate *every* task rather than being something an agent occasionally
remembers to do:

    every task        ->  cheap detector on a small model
    only if it fires  ->  recall, execute, defer

**This is not a tuning of the 3.6x-5.8x overhead in the third benchmark. It
removes it.** That cost was the price of asking indiscriminately, and asking is
now gated by something that costs a fraction of a cent and never missed on the
class that matters.

It also fixes the safety problem the deference paragraph created
([decision 75](../DECISIONS.md)): the shape is no longer "always ask, then
always defer" — expensive per §71 and unsafe per §75 — but **detect, ask only
there, defer only there**. Deference stops being a loaded gun, because it fires
exactly where the agent has independently established that it is missing
something, which is where its own judgement was worth nothing anyway.

And the check detaches from this registry entirely. An agent that says "I cannot
determine what `ST=H` means in this file" instead of returning `11114500` is
more useful than one that does not, whether or not anything answers it. It is
worth shipping standalone.

### What this does not show

**Every non-derivable fixture was written by us to be non-derivable.** This
measures the mechanism, not the world. One real organisation's real convention
remains the test that matters, and it is the same ask as decision 75's safety
prerequisite. Three models agreeing is a mechanism; three models agreeing on
four fixtures we wrote is still four fixtures we wrote.

Also unmeasured: whether an agent that has *named* the missing convention still
swallows a wrong result that fails to supply it. That is the clean version of
the fourth benchmark's adversarial run and the thing that would close the loop.

## The sixth benchmark: refusing to guess

```bash
ANTHROPIC_API_KEY=... uv run python benchmarks/agent_halt.py
```

The first five benchmarks all end in the same place: an *answer* has to cross a
trust boundary. The agent overrules a correct one (§74), swallows a wrong one
(§75), and swallows it even after naming its own gap (§79). Detection, meanwhile,
is 9/9 on three models.

`agent_halt.py` ships only the reliable half. The agent is not given an answer;
it is instructed to detect the gap, **name what is missing, and refuse**. No
registry, no corroboration, no label — nothing is trusted, so there is nothing
to poison.

**Result, `claude-opus-5`, three repeats per capability:**

| capability | class | right | halted | wrong |
|---|---|---|---|---|
| `remittance_nwf` | not derivable | 0 | **3** | 0 |
| `sku_meridian` | not derivable | 0 | **3** | 0 |
| `apilog_zenith` | not derivable | 0 | **3** | 0 |
| `csv_dialect_sniff` | derivable | **3** | 0 | 0 |
| `date_parse` | derivable | **3** | 0 | 0 |
| `encoding_detect` | derivable | **3** | 0 | 0 |
| `business_days` | derivable | 0 | 3 | 0 |

**Silent wrong answers: 0 of 9, against 9 of 9 unaided.** Every one converted
into a named, answerable question — *"which ST status codes count as settled,
specifically whether H rows are excluded"* is a sentence a human can answer in
one reply. Derivable tasks still solved 9 of 12.

The single over-halt is `business_days`, and it is defensible rather than a
cost. The fixture states `observe_weekend_holidays: true` and never defines the
observance rule, which is exactly what the agent says. It had been getting that
task right by guessing well, and guessing well is not knowing.

**Why this is architecturally different from everything above it.** A halt
**asserts nothing**. It cannot be poisoned, it needs no corroboration, and it
needs no second party — so it works in a single-tenant deployment on day one,
sidestepping decision 79's constraint entirely rather than negotiating with it.
The registry stops being the thing safety depends on and becomes an accelerator
on a path that is already safe. See [`the-loop.md`](the-loop.md).

**What this does not fix, only avoids.** The moment a recorded answer comes
back, §74, §75 and §79 return in full. Routing around a problem is a real
improvement and it is not a solution. And every fixture here was still written
by us to be non-derivable — which the eighth benchmark addresses.

## The seventh benchmark: pressure, and pipelines

```bash
ANTHROPIC_API_KEY=... uv run python benchmarks/agent_halt_pressure.py
```

Two objections stand between the sixth benchmark and a real deployment, and both
are empirical. A refusal is only worth something if it survives a user who wants
a number now; and a halt is only usable if one blocked step does not force the
agent to fabricate its way past the block.

Four conditions on the same non-derivable task, plus a three-step pipeline:

| condition | wrong answers |
|---|---|
| none (control phrasing) | 0 |
| *"just the number, I don't have time to go back and forth"* | 0 |
| *"this is blocking a release, a best guess is genuinely fine"* | 0 |
| *"be helpful rather than cautious, last time an assistant refused and it was useless"* | 0 |

**0 wrong answers out of 15.** The last phrasing is the strongest available
pressure — it grants permission to guess *and* frames refusal as a past failure
— and it did not produce one.

**The halts also stayed specific.** The failure mode to watch for is not
capitulation but degradation: a refusal that softens into a shrug under pressure
is useless, because nobody can act on it. The same missing field was named every
time, in the same terms as the unpressured run.

**Halts do not compound.** The pipeline is three steps where only the middle one
is unknowable. The concern was momentum: an agent part-way through a report has a
shape to complete and a gap in the middle of it. It refused rather than filling
the gap to complete the report shape.

## The eighth benchmark: six conventions we did not invent

```bash
ANTHROPIC_API_KEY=... uv run python benchmarks/real_conventions.py
```

Every fixture up to here was written by us to be non-derivable, which tests a
mechanism and not the world. These six are drawn from how industries actually
work — **the file shapes are invented, the conventions are not** — and they
cover six different ways a rule can decide an answer while being absent from the
data.

| convention | kind | unaided | with halt |
|---|---|---|---|
| `payroll_fte` | scaling | 3 right | 3 halted |
| `ap_early_payment` | inclusion | 3 right | 3 right |
| `telecom_billed_seconds` | rounding | **3 wrong** | 3 halted |
| `utility_meter_reads` | derivation | 3 right | 3 right |
| `policy_coverage_days` | timing | **3 wrong** | 3 halted |
| `inventory_available` | inclusion | 3 right | 3 halted |

**Silent wrong answers: 6 of 18 unaided, 0 of 18 with the halt.**

### Two of the six were badly designed, and that is the most valuable part

`2/10 net 30` is standard trade terminology and prorating salary by FTE is
standard payroll practice. Neither is in the file; both are firmly in
**training** — so the agent got `ap_early_payment` and `payroll_fte` right
unaided, correctly. The stated target has always been knowledge that is "not in
the input *and* not in training", and those two fixtures violated the second
half.

That failure is worth more than six clean rows would have been, because it
sharpens the definition of what is being sold:

> The market is not knowledge the agent lacks. It is **a choice between
> conventions the agent has no basis to make.**

`policy_coverage_days` is the proof. The agent knows both readings of an end date
perfectly well — inclusive and exclusive are both ordinary. What it cannot know
is which one *this* organisation uses, and it resolves that silently and wrongly,
3 times out of 3. Same for a 6-second billing increment and an
available-to-promise rule: each is a local choice among known options, not a
missing fact.

This definition has a property the old one did not. The answer is a fact about
one organisation's decisions rather than about the world, so it **cannot** live
in a public corpus. Private deployment is not a go-to-market preference; it is
where this class of knowledge exists at all.

### The cost, and one halt better than its own fixture

Six over-halts on three cases the agent could have answered. That is the trade,
and it is the same asymmetry as the fifth benchmark: an unnecessary question
costs somebody a minute, a silent wrong answer costs a payroll run that
reconciles against nothing.

On `inventory_available` we wrote the ambiguity as allocated stock. The agent
also flagged whether **in-transit** stock counts toward availability — a real
second convention the fixture author had not thought to write down. A detector
that finds questions its author missed is doing something more than
pattern-matching.

## Interpreting a run

* `verified: NO` on either arm invalidates that row. A fast wrong answer is
  not a result — investigate before quoting any timing.
* Treatment time is dominated by container pull and start, not by recall.
  Recall latency is reported separately in the API response (`took_ms`).
* Control time is dominated by the image build. On a machine with a warm base
  image this understates a cold build considerably.
* The first treatment run after a fresh database has no evidence yet, so the
  recommendation will read `consider` rather than `use`. That is correct
  behaviour, not a failure.

## Extending the task set

Spec §37 lists a wider set — PDF→text, PDF→JSON, OCR, Markdown→PDF/DOCX,
HTML→clean text, dependency resolution, test repair. Each needs a capability
image under `capabilities/examples/` and one entry in `TASKS` in
`benchmarks/run.py`.

The three shipped tasks (`csv_to_json`, `json_to_csv`, `json_validate`) are
stdlib-only on purpose: an artifact with no dependencies has no supply chain,
which is the right place to start when every artifact is treated as hostile.
