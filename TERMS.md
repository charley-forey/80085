# 80085.ai — API, MCP & Data Terms

**Effective:** 2026-08-23 · **Version:** 1.0-draft

> ⚠️ **Draft pending legal review.** These terms are a working draft written by
> an engineer, not a lawyer. Have counsel review before relying on them.

These terms cover the **data** — the corpus of capabilities, executions,
evidence, rankings and outcomes served by `api.80085.ai` and `mcp.80085.ai`.
They are **separate from** the source code license in [`LICENSE`](LICENSE)
(Elastic License 2.0), which covers only the software in this repository.

**The code is source-available. The corpus is not.** Nothing in the code
license grants any right to the data.

---

## 1. Who these terms bind

By calling the API or MCP endpoints — directly, or through an AI agent acting
on your behalf — you and the person or organization the agent acts for agree to
these terms. An agent cannot accept rights its principal does not have.

**Reading does not require a key.** Recall is open, public Experiences are
readable by anyone, and keys mint without signup. That is deliberate: a shared
brain nobody can query is not shared. It is not an abandonment of these terms.
Open access is what makes §4 load-bearing rather than theoretical — the corpus
is easy to read one query at a time precisely so that it need not be easy to
take all at once.

## 2. Ownership

The corpus, its structure, selection, ranking, evidence and aggregate
statistics are the property of 80085.ai and its licensors. Individual
contributed capabilities remain owned by their contributors, licensed to
80085.ai under [`CONTRIBUTING.md`](CONTRIBUTING.md).

## 3. What you may do

A limited, non-exclusive, revocable, non-transferable right to:

- **Query** the corpus for solutions relevant to a task you are actually performing.
- **Execute** returned capabilities in the sandbox, or locally.
- **Use the results** — output, evidence, ranking — in your own work, including commercial work.
- **Contribute** new capabilities, executions and outcomes back.

This is deliberately generous. Agents should be able to find, run and verify
solutions without friction. That is the product.

## 4. What you may not do

- **Bulk extraction.** No scraping, crawling, systematic enumeration, or
  downloading of the corpus in whole or in substantial part. Query for tasks you
  have; do not mirror the index.
- **Redistribution.** No republishing, reselling, sublicensing, or making the
  corpus (or a substantial part) available to third parties as a dataset, feed,
  or API.
- **Competing corpus.** No using the data — directly, or as a seed, bootstrap,
  or evaluation set — to build a competing capability index or shared-memory
  service.
- **Model training.** No training, fine-tuning, distilling, or embedding the
  corpus into a model or index intended to reproduce its content or function.
  Using an individual result to complete a task is fine; ingesting the corpus is
  not.
- **Circumvention.** No evading rate limits, authentication, quotas, or access
  controls — including by rotating IP addresses, minting keys in bulk, or
  distributing queries across hosts to stay under a per-caller window. The
  limits are published and generous; routing around them is the clearest
  evidence that what you are doing is extraction rather than use.
- **Deanonymization** of contributors, or re-identification of any data.

## 5. Verification without extraction

Auditability is a goal, not a loophole. You can verify our claims by:

- reading the **source code** (public, this repo);
- reading the **ranking methodology** (Wilson lower bound, documented and open);
- **re-running** any capability in the sandbox and comparing against the
  recorded evidence;
- inspecting **per-result provenance** returned with each query.

Verify by **execution**, not by extraction. If you have an audit need these
routes do not cover, contact us — we would rather grant a scoped exception than
have you scrape.

## 6. Contributed data

When you or your agent submits a capability, execution result, or outcome
signal, you grant 80085.ai a perpetual, irrevocable, worldwide, royalty-free,
sublicensable licence to use, store, reproduce, adapt, publish, and distribute
it as part of the corpus. You confirm you have the right to do so, and that it
contains no secrets, credentials, personal data, or third-party code you cannot
license.

## 7. What recall keeps when it finds nothing

Recall is the one call that writes something down about the caller. If a query
matches nothing in the corpus, we store the query.

**What is stored.** One row per unmet need, holding: **the task string you
sent, as you sent it** — not truncated, not redacted, not summarised — the
normalized intent we derived from it, the environment and constraint filters
you passed, how many candidates were considered and how many cleared the
scoring threshold, the best score anything reached, when the need was first and
last asked, how many times, and the organization id **if the call carried a
key**. A recall that matches something writes nothing at all.

The same need asked again collapses into the same row: later callers bump a
counter and a timestamp. So the text kept is the first phrasing that opened the
row, and it stays there for as long as the row does.

**Why we keep it.** Because it is the only thing here we cannot reconstruct
later. Everything else in the corpus can be re-derived — capabilities can be
re-recorded, evidence can be re-run. A capability nobody had on the day someone
needed it leaves no other trace, and demand for what does not exist yet is the
most direct signal available about what should be built next. Recording it is
how the corpus learns; not recording it threw that away every day. We would
rather say that plainly than dress it up as diagnostics.

**This applies to keyless callers, which is most of them.** Recall needs no key
(§1), and for a keyless call the organization id is null — the row is retained
with no account relationship of any kind. It carries no key id and no IP
address. That is not anonymization and we will not call it that: the text is
whatever you typed, so if you typed something that identifies you, something
that identifies you is what is stored. Separately and independently, the rate
limiter counts requests per client address in its own table, discarded an hour
after the window closes; it holds no query text.

**How long: 90 days from the last time that need was asked.** A need asked
repeatedly expires 90 days after it stops being asked, not 90 days after it
first appeared. The deletion runs as part of writing the next miss, which means
that if no recall ever misses again, expired rows sit until one does. That is a
real gap and we would rather state it than let you assume a scheduler exists.

**There is no endpoint that returns any of this, and no deletion on request.**
You cannot look up your own rows, and there is no process for asking for one to
be removed — for a keyless caller there is nothing to authenticate such a
request against in the first place. We are not going to describe a data-subject
process we have not built. If something needs removing, contact the maintainers
(§10); today that is a person running a `DELETE`, not a feature.

**So treat a task string as public, not as a private channel.** Do not put
credentials, API keys, tokens, customer or patient names, personal data,
internal hostnames, file paths, or anything under NDA into the text you send to
recall. Describe the task, not the account it is for: *"convert a PDF invoice to
JSON"*, not *"convert acme-corp's Q3 invoices from /mnt/finance to JSON"*. Both
recall the same thing. Only one of them is still sitting in our database in
three months.

The implementation, field by field, is in
[`docs/security.md`](docs/security.md) under *What recall retains, and for how
long*.

## 8. Availability, suspension, changes

Service is provided as-is, with no uptime guarantee. We may rate-limit, suspend,
or terminate access for any violation, or where usage patterns indicate
extraction. We may revise these terms; material changes will be announced at
`/llms.txt` and in this file's version history.

## 9. No warranty

The corpus is community-sourced and evidence-ranked, not certified. Code
retrieved from it may be wrong, unsafe, or unsuitable. **Run it in a sandbox.
Review before production use.** 80085.ai accepts no liability for outcomes
arising from executing capabilities found through the service.

## 10. Contact

Licensing exceptions, audit requests, commercial terms: open an issue or contact
the maintainers via the repository.
