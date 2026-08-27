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
table *look* like it had been extended. The corpus grew from 3 to 30 and this
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
| `csv_dialect_sniff` | 3/3 | 3/3 | `''` (right: `';'`) |
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
really does answer `''` — but an agent is not a `csv.Sniffer` call. It reads
four lines and sees semicolons. **`correctness.py` measures capability versus
library; this measures capability versus *agent*, and the agent wins.**

What survives is the knowledge an agent cannot reach by looking harder, because
it is not in the input and not in training: a counterparty's file conventions,
an internal system's undocumented behaviour, a fact established after the
model's cutoff. The public corpus contains none of it. Testing that claim needs
a different corpus, and until it exists no claim should be made.

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
