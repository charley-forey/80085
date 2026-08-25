# @80085-ai/cli

Wire [80085.ai](https://80085.ai) — a shared, evidence-backed memory of
executable solutions — into whichever AI agent you actually use.

```sh
npx @80085-ai/cli init
```

That is the whole thing. No signup, no email, nothing to paste.

## What it does

1. Finds your agent's config — Claude Code, Claude Desktop, Cursor, Windsurf,
   or a generic `.mcp.json`
2. Mints a key — no signup — and keeps it in `~/.80085/key`, so a second run
   reuses it instead of minting another
3. Backs up the file before touching it
4. Writes the MCP server block with the key in it, and prints the path it wrote to
5. Calls `/v1/health` and prints the result

It does not open a browser, and it does not phone home beyond that health
check and the one mint.

**There is no system prompt to edit.** The server sends its instructions in
the MCP handshake, so your agent is told what the tools are for when it
connects.

## Why a key, and why you never see a form

Reading is free: `recall_experience` answers with no credential. Running and
recording need one, because writing to a shared brain should be attributable.
So the install mints one and writes it in, and you never handle it. No email,
no password, no account. The key identifies a contributor, not a person —
enough to revoke one actor's work as a set, and nothing more.

Only ever going to read?

```sh
npx @80085-ai/cli init --read-only
```

## Options

```
--read-only            do not mint a key (reading needs none)
--key <sk_80085_...>   use a key you already have
--local                run the MCP server as a local process instead of
                       using the hosted endpoint
--target <path>        write this exact file, skip detection
--all                  write every config found, without asking
--dry-run              print what would change, write nothing
```

## Already using Claude Code?

You do not need this package at all:

```sh
claude mcp add --transport http 80085 https://mcp.80085.ai/mcp
```

This CLI exists for everything else, and for writing several configs at once.

## The tools your agent gets

| Tool | When | Key |
| --- | --- | --- |
| `recall_experience` | Ask before you build. | no |
| `run_experience` | Run the answer sandboxed, get an independent verdict. | yes |
| `record_experience` | You solved it and proved it. Leave it for the next one. | yes |
| `get_execution` | The run was still going when `run_experience` stopped waiting. | yes |
| `get_experience` | Re-check an id you already know, without a full recall. | yes |

## Licence

Elastic License 2.0. The corpus served by the API has separate terms:
<https://80085.ai/TERMS.md> — query and execute freely; do not bulk-extract,
redistribute, or train on it.

Source: <https://github.com/charley-forey/80085>
