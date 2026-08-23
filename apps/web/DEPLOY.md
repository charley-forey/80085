# Deploying 80085.ai

There are two ways to serve this site, and the repo supports both.

**Railway (working today).** The API image builds `apps/web` in a Node stage
and serves the result, with the same content negotiation the Vercel host does
— `_representation()` in `apps/api/src/boobs_api/main.py` mirrors the rewrite
table in `vercel.json`. Point the apex at Railway and the site is live. This
is the shortest path and needs nothing that is not already provisioned.

**Vercel (the better long-term home).** Preview deploys per PR, instant
rollback, and the marketing page stops sharing a blast radius with the API.
Blocked on connecting GitHub to Vercel — see §2.

Either way `api.80085.ai` stays on Railway.

## 1. DNS — at the registrar

`80085.ai` is registered but currently parked (it serves a 114-byte redirect to
`/lander`). Replace the parking records with these.

| Host  | Type  | Value                     | For                        |
| ----- | ----- | ------------------------- | -------------------------- |
| `api` | CNAME | `3b5l44ej.up.railway.app` | Railway — the API          |
| `@`   | ALIAS | see below                 | whichever host serves the site |
| `www` | CNAME | same as `@`               | redirect to apex           |

The `api` record is exact: Railway issued it when the custom domain was
attached, and its certificate stays in `VALIDATING_OWNERSHIP` until DNS
resolves.

For the apex, pick one:

- **Railway** — attach `80085.ai` to the `api` service and use the CNAME
  target Railway returns. Apex CNAMEs need an ALIAS/ANAME record, which most
  registrars support; if yours does not, use Railway's A record.
- **Vercel** — `A @ 76.76.21.21` and `CNAME www cname.vercel-dns.com`. Confirm
  against the dashboard when you add the domain; Vercel moves the apex IP
  occasionally.

Verify:

```bash
curl -s https://api.80085.ai/v1/health      # {"status":"ok"}
curl -s https://80085.ai | head -5          # the seven-segment wordmark
```


## 2. Vercel — connect GitHub first

Creating the project over the API failed: it reports success, then every read
of the project 404s. The cause is that **Vercel has no GitHub connection on
this account**, so the git link cannot be established.

Two orphaned project records may exist from those attempts, `80085` and
`80085-ai`. Delete whichever show up before creating the real one.

1. Vercel dashboard → **Settings → Git → Connect GitHub**, and grant access to
   `charley-forey/80085`.
2. **Add New → Project** → import `charley-forey/80085`.
3. Set **Root Directory** to `apps/web`. Framework preset: **Other**. Leave
   build and output alone — `vercel.json` already sets
   `buildCommand: node build.mjs` and `outputDirectory: public`.
4. Add the domains `80085.ai` and `www.80085.ai`, with `www` redirecting to the
   apex.

Environment variables (Production):

| Name                | Value                       | Why                                  |
| ------------------- | --------------------------- | ------------------------------------ |
| `API_URL`           | `https://api.80085.ai`      | the recall proxy's upstream          |
| `RECALL_PUBLIC_KEY` | a read-only key, see §3     | terminal-mode live recall            |

Without `RECALL_PUBLIC_KEY` the proxy returns 503 and terminal mode says live
recall is not wired up. Everything else works.

## 3. The read-only key

`/v1/bootstrap` now takes an optional `scopes`. Mint a key that can read and
nothing else — it is exposed to anyone who opens the terminal on the homepage,
so it must not be able to execute, record, or verify:

```bash
curl -X POST https://api.80085.ai/v1/bootstrap \
  -H 'content-type: application/json' \
  -d '{"organization":"public","agent":"website","token":"<BOOBS_BOOTSTRAP_TOKEN>","scopes":["experiences:read"]}'
```

Put the returned `api_key` in `RECALL_PUBLIC_KEY`. It is the only time the
plaintext exists.

## 4. Verify the preview before promoting

The representation matrix is the thing to check — §18 of the design spec calls
a cross-served representation the most likely production bug in the build.

```bash
U=https://<preview>.vercel.app

curl -s $U | head -40                          # ANSI wordmark, under 40 lines
curl -s -H 'Accept: text/markdown' $U          # markdown
curl -s -A ClaudeBot $U | head -5              # markdown
curl -s -A 'Mozilla/5.0' -H 'Accept: text/html' $U | head -3   # HTML
curl -sD- -o/dev/null $U | grep -i '^vary'     # Accept, User-Agent

# the cross-serve check: same edge, different clients, different bodies
curl -s -A 'Mozilla/5.0' -H 'Accept: text/html' $U -o /tmp/a
curl -s -A curl/8.4.0 $U -o /tmp/b
cmp /tmp/a /tmp/b && echo 'BUG: CDN cross-served' || echo 'ok: distinct'
```

Then: `/llms.txt`, `/llms-full.txt`, `/agents.md`, `/.well-known/mcp.json` and
`/openapi.json` all 200; Lighthouse 100 on mobile and desktop; CLS 0.00 while
mashing the keypad; the page readable and the install completable with
JavaScript disabled.

The real test, from §19: point a fresh agent at the preview with no other
context and ask it to install the MCP server. If it cannot succeed without
help, the machine layer is not done.

## 5. The CLI

`@80085/cli` needs the npm org `@80085` to exist and be owned by you.

```bash
cd apps/cli
npm publish --access public
```

Until then it is testable with `npm link`, or directly:

```bash
node apps/cli/init.js init --target ./.mcp.json --key sk_80085_...
```
