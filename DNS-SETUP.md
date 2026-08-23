# DNS setup at GoDaddy — 80085.ai

> **Status: done.** Both records are propagated, both certificates are issued,
> and both hostnames are serving. `api.80085.ai` and `mcp.80085.ai` are live,
> and the MCP service and worker are pointed at `https://api.80085.ai`.
> Kept for reference and for whoever sets up the next environment.

Both custom domains are attached on the Railway side. What was needed was
four DNS records in GoDaddy. Railway issues the TLS certificate automatically
once it sees them.

## Records to add

GoDaddy → your domain → **DNS** → **Manage Zones** → **Add New Record**.

In GoDaddy, **Name** is just the subdomain label — do *not* type the full
domain, and do not add a trailing dot.

### 1. api.80085.ai → the API

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `api` |
| Value | `3b5l44ej.up.railway.app` |
| TTL | 1 hour (default) |

| Field | Value |
|---|---|
| Type | `TXT` |
| Name | `_railway-verify.api` |
| Value | `railway-verify=363408a1260220ba2e1b2b758b06d0dfa7249256963ada0be66dce4feaf7fa6d` |
| TTL | 1 hour |

### 2. mcp.80085.ai → the MCP server

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `mcp` |
| Value | `lx53z56p.up.railway.app` |
| TTL | 1 hour |

| Field | Value |
|---|---|
| Type | `TXT` |
| Name | `_railway-verify.mcp` |
| Value | `railway-verify=871b14e6ceb1cd60ab0e1fbc5587d7dd4fc2e7a748f3f6f7461a33249be74eb0` |
| TTL | 1 hour |

The CNAME targets are **not** the `*-production-*.up.railway.app` service
domains — Railway issues a separate short hostname per custom domain. Use the
values above exactly.

### Leave alone

Whatever Vercel had you add for `www.80085.ai` and the apex. Those are a
different host and must not be touched. There is no conflict: `api` and `mcp`
are distinct labels.

## Verifying

DNS usually propagates in 5–30 minutes; GoDaddy can take up to an hour.

```bash
# 1. DNS resolves to Railway
nslookup api.80085.ai
nslookup mcp.80085.ai

# 2. Railway sees the records and issued a certificate
railway domain status api.80085.ai --service api
railway domain status mcp.80085.ai --service mcp
#    look for verified: true and CERTIFICATE_STATUS_TYPE_ISSUED

# 3. The API answers on the real hostname
curl https://api.80085.ai/v1/health
curl https://api.80085.ai/v1/ready
#    expect: {"ready":true,"checks":{"database":true,"pgvector":true,"object_storage":true},...}

# 4. The whole product loop, against the real hostname
uv run python scripts/smoke.py --url https://api.80085.ai --token "$BOOBS_BOOTSTRAP_TOKEN"
#    expect: all checks passed -- the reuse loop works on this deployment
```

For the MCP endpoint (it speaks MCP, not plain HTTP, so `curl` alone is not a
useful test):

```bash
uv run python scripts/check_mcp.py --url https://mcp.80085.ai/mcp --key sk_80085_...
```

## After DNS is live — done

1. ~~**MCP → API.**~~ `BOOBS_API_URL=https://api.80085.ai` is set on the
   Railway `mcp` service.
2. ~~**Worker.**~~ Restarted against `https://api.80085.ai`.
3. **The website.** `www.80085.ai` should link to
   `https://api.80085.ai/llms.txt` and `https://mcp.80085.ai/mcp` as the
   integration endpoints. *(Still to do — Vercel side.)*

Verified after the switch: the full smoke test passes against
`https://api.80085.ai`, and a real MCP session against `https://mcp.80085.ai/mcp`
recalls, executes and verifies end to end.

**Note on the TXT records:** both were created with a leading space inside the
value (`" railway-verify=..."`). Both verified anyway, so no action is needed;
worth knowing if a future record does not verify.

## Plan limit worth knowing

The Railway workspace is on **Hobby**, which allows **2 custom domains** — and
`api` plus `mcp` uses both. A third (say `registry.80085.ai`) needs a plan
upgrade. The artifact registry stays on its Railway hostname until then, which
is fine: it is referenced by digest inside Experience records, not typed by
humans.
