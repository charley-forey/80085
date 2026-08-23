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

To make these numbers mean more, in order of value:

1. Drive both arms with a real coding agent and measure wall clock, tokens and
   tool calls (§38's full metric set).
2. Add tasks where the artifact is genuinely expensive to produce — OCR,
   PDF layout extraction, a dependency-resolution loop — instead of three
   stdlib converters.
3. Measure the cold path: no base image cached, as a new environment would
   experience it.

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
