# Setting this up for your organisation

One page. Fifteen minutes. You need a terminal and somebody who can say what
your conventions are.

---

## The shape

```
  your organisation                        ← provisioned once
    ├── admin key                          ← you keep this. it issues the others.
    ├── priya   ─┐
    ├── dev      ├── one key each          ← every question and answer is theirs
    └── nightly-etl ─┘                        by name

  a question priya answers  →  serves priya's agent immediately
                            →  serves everyone once somebody verifies it
```

Three rules, and they are the whole security model:

1. **A key is a person or a system, never a team.** Everything it asks and
   answers is attributed to it, and revoking it should cost nobody else.
2. **An answer serves its own agent until a second human verifies it.** One
   person's sentence in one chat is not yet a fact about your company.
3. **Nothing crosses an organisation boundary.** Ever. Your conventions are
   facts about your company's decisions, which is why they cannot come from
   anywhere else and will not go anywhere else.

## Step 1 — get your organisation

No signup, no email, nobody at our end.

```bash
curl -X POST 'https://api.80085.ai/v1/keys?label=acme'
```

That is your organisation and your founder key, in one call. Keep it where you
keep other root credentials: it is the only key that can issue more, and there
is no account to recover it into.

Self-hosting instead? [`private-deployment.md`](private-deployment.md) — the
same commands against your own host, and nothing leaves your network.

## Step 2 — issue a key per person

```bash
curl -X POST https://api.80085.ai/v1/agents \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name": "priya"}'
```

Use the name a colleague would use. It appears on every question that key asks
and every answer it gives, and *"who said this was true"* is the question
somebody will eventually ask about a number that turned out wrong.

**Provisioned keys cannot provision.** A team lead handing out keys should not
be handing out the ability to hand out keys — that is how an organisation stops
being able to say who can do what. Widening a key means coming back to the admin
credential, deliberately a heavier door.

## Step 3 — each person points their agent at it

```bash
claude mcp add --transport http 80085 https://mcp.80085.ai/mcp \
  --header "Authorization: Bearer $THEIR_KEY"
```

Cursor, Windsurf, or anything else that speaks MCP:

```json
{ "mcpServers": { "80085": {
    "url": "https://mcp.80085.ai/mcp",
    "headers": { "Authorization": "Bearer <their key>" } } } }
```

That is the setup finished.

## What actually happens then

**The agent halts.** Somebody asks it for a number, it notices the answer turns
on a convention it has no basis to choose, and it stops:

> *"I cannot determine whether `ST=H` rows count as settled in this remittance
> advice."*

**They answer it where they already are.** In the agent's own chat, because they
are sitting there watching it work. No dashboard, no ticket, no waiting on a
channel — routing the answer through somewhere else would make halting cost more
than guessing, and then people would turn it off.

**It is theirs immediately.** That agent carries on with the answer. The person
who needed the number gets the number.

**Somebody verifies it, and then it is everyone's.**

```bash
curl -H "Authorization: Bearer $ADMIN_KEY" \
  https://api.80085.ai/v1/answers/awaiting-verification

curl -X POST https://api.80085.ai/v1/answers/<id>/verify \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' -d '{"verified_by": "sam"}'
```

Post that queue to a channel, wire it to a dashboard, or open it on a Friday.
We do not care which, and deliberately do not ship one — the queue is an API
because your approval process is yours.

**Nobody asks again.** The next agent to hit the same question, phrased however
it likes, gets the answer instead of stopping.

## The one report worth reading

```bash
curl -H "Authorization: Bearer $ADMIN_KEY" \
  https://api.80085.ai/v1/questions/unanswered
```

What your agents are stuck on, most-asked first. **A question asked forty times
and never answered is the most expensive row in your database** — forty runs
that stopped, or worse, forty that did not because somebody turned the halt off.

Read it weekly. It is also the only honest list of what your organisation knows
but has never written down.

## Choosing who verifies

We cannot tell two humans apart, so the separation between *"the person who
answered"* and *"the person who verified"* is procedural rather than enforced.
Saying so is more useful than implying a check that does not exist.

What works:

* **The person who owns the data.** Whoever would be asked in a meeting is the
  right verifier, and usually is not the engineer whose agent halted.
* **Two names on anything that touches money.** Payroll, settlement, billing.
* **Nobody verifying their own answer**, as a rule people follow rather than a
  rule we enforce.

Since agents are instructed to defer to a verified answer, verification is the
moment a sentence becomes something nobody re-checks. Treat it accordingly.

## Common questions

**Does our data leave?** No. Questions and answers are scoped to your
organisation and never matched across a boundary — there is a test that fails
if that ever stops being true. For total isolation, self-host.

**What if an answer turns out wrong?** Answer it again. The new one supersedes
the old immediately and the old one stays, because an answer that turned out
wrong is the row somebody most needs to find.

**What does it cost when an agent halts unnecessarily?** Somebody's minute. What
it costs when an agent guesses is a wrong number nothing downstream questions.
We tuned for the first (see [`benchmarks.md`](benchmarks.md)) and would again.

**Can we start without any of this?** Yes, and you should. The halt itself is a
paragraph in a system prompt and needs no account at all — that is the entire
safety benefit, free, today. Everything here is about not answering the same
question twice.
