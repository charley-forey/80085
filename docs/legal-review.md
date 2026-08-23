# Legal review pack — licensing & terms

**For:** external counsel · **Prepared by:** engineering · **Date:** 2026-08-23

Everything in this repo's licensing layer was drafted by an engineer, not a
lawyer. This file exists so the review is cheap and targeted: what we did, why,
and the specific questions we know we can't answer ourselves.

**The "pending legal review" framing on `TERMS.md` still holds, and has more
work to do than when it was written.** Nothing here has been reviewed, and the
product has since begun retaining free text supplied by anonymous callers
(Q12), which is a category of obligation this pack was not originally written
to cover. The draft warning stays until counsel has actually read it.

## What's in place

| File | Covers | Instrument |
|---|---|---|
| [`LICENSE`](../LICENSE) | the source code | Elastic License 2.0, verbatim |
| [`TERMS.md`](../TERMS.md) | the corpus served by `api.80085.ai` / `mcp.80085.ai` | bespoke draft, `1.0-draft` |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | inbound rights from contributors | bespoke draft |
| [`TRADEMARK.md`](../TRADEMARK.md) | the name and marks | policy statement, nothing registered |

**Design premise:** the code is not the moat, the corpus is. So the code is
deliberately permissive-but-not-open (ELv2 blocks a competing hosted service,
nothing else), and the real restrictions live in `TERMS.md`, which binds API
callers by contract rather than by copyright.

---

## Blocking questions — we think these need answering first

### 1. There is no legal entity
`LICENSE` names the licensor as "80085.ai", which is a domain, not a person or
company. **Who actually owns this IP, grants these licences, and would sue?**
Until there's an entity, the copyright notice is arguably naming nobody, the
inbound contributor grant runs to nobody, and there's no one to enforce the
trademark. We assume this is the first thing to fix.

### 2. Is `TERMS.md` actually formed against API callers? *(now harder — see below)*
Keys are **no longer issued by hand**. As of the open-access change, recall
requires no key at all, public Experiences are readable by anyone with `curl`,
and `POST /v1/keys` mints without signup. There is therefore **no moment of
assent** for most callers. Questions:
- Against an anonymous `curl` caller who never saw `TERMS.md`, is anything
  formed at all? Our working assumption is *no*, or close to it.
- If nothing is formed, what actually protects the corpus against a
  determined reader — technical limits, database right, something else?
- Would gating *bulk-ish* access (rather than all access) behind assent
  restore a contract without closing the product? What is the least-friction
  point at which assent becomes meaningful?
- Does the notice we now give — `Link: rel="terms-of-service"` on every
  response, plus the MCP handshake instructions — do any legal work, or is it
  just good manners?

### 3. Governing law and venue are missing
`TERMS.md` specifies neither. We didn't want to guess a jurisdiction. Needs
deciding alongside Q1.

### 4. Can an AI agent bind its principal?
`TERMS.md` §1 asserts that calling the API through an agent binds the person or
org the agent acts for. This is the novel part and we are least confident here.
Standard agency law presumably applies, but the caller may be an autonomous
process with no human in the loop at request time. Is the assertion sound? Does
it need to be backed by the key-issuance assent in Q2 to mean anything?

---

## ⚠️ Open access changed the picture after these terms were drafted

`TERMS.md` was written for a keyed API. The product then moved to open access,
and three of its premises weakened. Flagging explicitly so the review isn't
done against a stale mental model:

1. **No assent for most callers.** See Q2 above. This is the biggest change.
2. **Trade secrecy is gone for public content.** Experiences now default to
   **public** on record. Anything public is outside trade-secret protection
   permanently, and that cannot be walked back for material already published.
   Our remaining claims over the corpus are compilation copyright (thin) and,
   if we have EU nexus, database right — which makes Q6 more load-bearing than
   it looked.
3. **We used to explicitly invite the crawling we forbid — now fixed.**
   `robots.txt` said `Allow: /` to GPTBot, ClaudeBot, PerplexityBot,
   Google-Extended and CCBot, with no exclusions, while `TERMS.md` §4 forbade
   bulk extraction. That was a contradiction on its face and a defendant would
   have led with it.

   It now allows the marketing surface and disallows the corpus endpoints
   (`/recall`, `/v1/`), with those exclusions repeated in **every** named
   crawler group — necessary because `robots.txt` groups do not inherit: a
   named `User-agent` group replaces the `*` group rather than adding to it,
   so exclusions placed only under `*` would have left exactly those five
   crawlers still openly invited.

   Remaining question for you: the corrected file states the position going
   forward, but the earlier invitation was public for some period. **Does the
   fix cure it prospectively only?** Is there anything we should do about
   material crawled while the permissive version was live — and does the prior
   invitation weaken §4 against a party who relied on it at the time?

4. **We started storing user-supplied free text.** Recall misses persist the
   caller's own words, from callers with no key and no account. That is new
   since this pack was written and is Q12 below. It is the one change that
   moves us from "what protects our data" to "what obligations do we owe over
   theirs", which is a different body of law than the rest of this file.

Also worth a view: contributors now record **public by default**. Is
`CONTRIBUTING.md` / `TERMS.md` §6 clear enough that a contributor understands
their submission becomes world-readable, or does default-public need explicit
notice at the point of recording?

---

## Substantive questions on the restrictions

### 5. The model-training prohibition
`TERMS.md` §4 forbids training, fine-tuning, distilling, or embedding the
corpus. Is a contractual prohibition on training enforceable, and does it
survive a copyright-preemption argument given that much of the corpus is facts
and short code snippets that may not be copyrightable individually?

### 6. What protects the corpus, actually?
Our understanding, which we'd like confirmed or corrected:
- **US:** *Feist* — facts aren't copyrightable; a compilation gets thin
  protection in its selection and arrangement only. No sui generis database right.
- **EU/UK:** database right may apply given substantial investment in obtaining
  and verifying contents — plausibly our strongest claim, if we have EU nexus.
- Which regime do we actually sit in, and does that change where we should
  incorporate or host?

### 7. Anti-extraction clauses vs. competition law
§4 forbids using our data to build a competing index. Any risk this is read as
an unreasonable restraint, particularly in the EU?

### 8. Contributor grant without a signature
`CONTRIBUTING.md` asserts that opening a PR accepts a broad, sublicensable,
relicensable grant. Is "opening a PR" sufficient assent? Should we move to a
DCO, a signed CLA, or a bot-enforced click? We chose the lightweight version to
avoid friction — tell us if that's false economy. Note we deliberately took a
*licence*, not an assignment; confirm that's still enough to relicense or sell.

### 9. Contributed content we didn't vet
Contributors submit executable code and execution traces. Risks we can see:
third-party code submitted without rights, secrets or credentials pasted into a
capability, personal data in execution logs. `TERMS.md` §6 and
`CONTRIBUTING.md` push the warranty onto the contributor. Is that sufficient,
and what's our takedown obligation once on notice?

Note that Q12 is the same risk arriving through a path where that warranty
cannot apply, because the person supplying the text is not a contributor and
agreed to nothing.

### 10. We execute untrusted code on users' behalf
The sandbox is hardened (no network, no root, read-only fs, and there's an
escape-attempt suite), but the product's core loop is *running code a stranger
wrote*. `TERMS.md` §9 disclaims liability. Does that disclaimer hold up, and
does it need different wording for consumers vs. businesses?

### 11. Data protection
If any execution trace or contributed capability contains personal data, GDPR /
UK GDPR obligations attach. We have no privacy policy and no stated lawful
basis. We now do have a retention position, but only for one table — see Q12,
which has overtaken this as the sharper version of the same question. Is a
privacy policy needed before self-serve signup?

### 12. We store free text typed by anonymous callers
`recall_misses` records every recall that matches nothing, and the row includes
**the caller's raw task string, stored as sent** — untruncated, unredacted —
alongside the normalized intent, the filters, candidate counts, first/last seen
and an occurrence counter. Retention is 90 days from last occurrence, swept
when the next miss is written. This is now disclosed in `TERMS.md` §7 and
documented field by field in [`security.md`](security.md); it was shipped
before either said anything, which is the reason §7 exists.

The engineering case for keeping it is genuine — unmet demand is the one
dataset that cannot be backfilled — but the legal shape is the worst
combination we have:

- **No key, so no account, so no assent and no relationship.** This is Q2's
  problem with the consequences reversed: there we worried that nothing binds
  the caller, here nothing we can point to permits *us*. What is the lawful
  basis for processing free text supplied by a person who was never shown a
  term and holds no account? Is legitimate interest available, and does the
  fact that the field is free-form — so its contents are entirely the caller's
  choice — help or hurt?
- **No subject access, no erasure, no way to find a row.** No endpoint returns
  a miss, there is no deletion-on-request path, and for a keyless caller there
  is nothing to authenticate such a request against. `TERMS.md` §7 says this
  outright rather than implying a process. If a DSAR arrives naming a string,
  can we answer it, and does the inability to identify a data subject help us
  (Art. 11) or expose us?
- **We can't tell whether any of it is personal data.** It is whatever an agent
  typed. Most of it will be "convert a PDF to JSON"; some fraction will not be.
  Does storing a field whose contents we cannot characterise change the
  analysis, and is the honest answer to truncate or hash the raw text rather
  than to keep drafting around it? Engineering's view is that the demand signal
  lives in the normalized intent, not the raw phrasing, so truncation is
  cheaper than it looks — we would like that confirmed as the right remedy
  before doing it.

Related: retention is enforced by a delete that runs when the next miss is
recorded, so an idle deployment can hold expired rows past 90 days. Disclosed.
Is "90 days, subject to the next write" a defensible retention position or does
it need a scheduler behind it to be one?

---

## Lower priority, but on the list

- **ELv2 is not OSI-approved.** Accepted trade-off — but it does get flagged in
  some enterprise procurement. Confirm it's the right call.
- **Trademark.** Nothing filed. `80085` is numeric and may be weak on
  distinctiveness — see [`TRADEMARK.md`](../TRADEMARK.md) §5. Needs a clearance
  search before any filing.
- **Export control / sanctions.** Should key issuance screen?
- **Sub-processors.** Hosting, object storage and any model provider touch
  corpus data; likely needs disclosure once a privacy policy exists.

---

## What we are *not* asking

We're not asking whether to be open source. That decision is made and the
reasoning is in PR #7: the corpus is the asset, the code is inert without it,
and we'd rather have contributors and integrations than a licence that stops a
fork nobody would run anyway.
