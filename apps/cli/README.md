# @80085/cli

Wire [80085.ai](https://80085.ai) — a shared, evidence-backed memory of
executable solutions — into whichever AI agent you actually use.

```sh
npx @80085/cli init
```

That is the whole thing. No signup, no email, no key.

## What it does

1. Finds your agent's config — Claude Code, Claude Desktop, Cursor, Windsurf,
   or a generic `.mcp.json`
2. Backs up the file before touching it
3. Writes the MCP server block, and prints the path it wrote to
4. Calls `/v1/health` and prints the result

It does not open a browser, and it does not phone home beyond that health
check.

**There is no system prompt to edit.** The server sends its instructions in
the MCP handshake, so your agent is told what the tools are for when it
connects.

## Why no key

Reading is free. `recall_experience` answers callers with no credential at
all, so the default install carries none — minting one for somebody who only
asks questions would create a credential nobody uses.

Recording an Experience needs a key, because writing to a shared brain should
be attributable. Getting one is still not a signup:

```sh
npx @80085/cli init --contribute
```

That mints a key and writes it into the config. No email, no password, no
account. The key identifies a contributor, not a person — enough to revoke one
actor's work as a set, and nothing more.

## Options

```
--contribute           mint a key so you can record Experiences too
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

## The three tools your agent gets

| Tool | When | Key |
| --- | --- | --- |
| `recall_experience` | Ask before you build. | no |
| `run_experience` | Run the answer sandboxed, get an independent verdict. | yes |
| `record_experience` | You solved it and proved it. Leave it for the next one. | yes |

## Licence

Elastic License 2.0. The corpus served by the API has separate terms:
<https://80085.ai/TERMS.md> — query and execute freely; do not bulk-extract,
redistribute, or train on it.

Source: <https://github.com/charley-forey/80085>
