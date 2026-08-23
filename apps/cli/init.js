#!/usr/bin/env node
/**
 * npx @80085/cli init
 *
 * Wires the 80085 MCP server into whichever agent you actually use.
 *
 * It does not mint credentials for you, open a browser, or phone home. It
 * finds the config, shows you what it is about to write, backs the file up,
 * writes it, and verifies the API answers. Everything it did is printed.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir, platform } from 'node:os';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { stdin, stdout } from 'node:process';
import { pathToFileURL } from 'node:url';

export const REPO = 'https://github.com/charley-forey/80085';
export const DEFAULT_API = 'https://api.80085.ai';
const KEY_PREFIX = 'sk_80085_';

/** Every config we know how to write, in the order we prefer them. */
export function targets(os = platform(), env = process.env, home = homedir()) {
  const desktop =
    os === 'win32'
      ? join(env.APPDATA || join(home, 'AppData', 'Roaming'), 'Claude', 'claude_desktop_config.json')
      : os === 'darwin'
        ? join(home, 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json')
        : join(env.XDG_CONFIG_HOME || join(home, '.config'), 'Claude', 'claude_desktop_config.json');

  return [
    { name: 'Claude Code', path: join(home, '.claude.json') },
    { name: 'Claude Desktop', path: desktop },
    { name: 'Cursor', path: join(home, '.cursor', 'mcp.json') },
    { name: 'Windsurf', path: join(home, '.codeium', 'windsurf', 'mcp_config.json') },
    { name: 'this project', path: join(process.cwd(), '.mcp.json') }
  ];
}

export function serverBlock(key, apiUrl = DEFAULT_API) {
  return {
    command: 'uvx',
    args: ['--from', `git+${REPO}#subdirectory=apps/mcp`, '80085-mcp'],
    env: { BOOBS_API_URL: apiUrl, BOOBS_API_KEY: key }
  };
}

/**
 * Merge our server into an existing config without disturbing anything else.
 *
 * Every client we support uses the same `mcpServers` shape, so there is one
 * merge rather than one per client.
 */
export function mergeConfig(existing, block) {
  const next = { ...(existing ?? {}) };
  next.mcpServers = { ...(next.mcpServers ?? {}), 80085: block };
  return next;
}

const read = (path) => {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return undefined; // exists but is not JSON — refuse to touch it
  }
};

const ok = (s) => `  \x1b[1m✓\x1b[0m ${s}`;
const bad = (s) => `  \x1b[1m✗\x1b[0m ${s}`;
const dim = (s) => `\x1b[2m${s}\x1b[0m`;

const HELP = `
  80085 — wire the shared brain into your agent.

    npx @80085/cli init [options]

  Options
    --key <sk_80085_...>   your API key (otherwise you are asked)
    --api-url <url>        default ${DEFAULT_API}
    --target <path>        write this exact file, skip detection
    --all                  write every config found, without asking
    --dry-run              print what would change, write nothing
    --help                 this

  No key? Self-serve signup is not built yet. https://80085.ai/key
`;

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') args.help = true;
    else if (a === '--all') args.all = true;
    else if (a === '--dry-run') args.dryRun = true;
    else if (a === '--key') args.key = argv[++i];
    else if (a === '--api-url') args.apiUrl = argv[++i];
    else if (a === '--target') args.target = argv[++i];
    else args._.push(a);
  }
  return args;
}

/** Ask for the key without echoing it into the scrollback. */
async function askKey(rl) {
  const mute = { muted: false };
  const write = stdout.write.bind(stdout);
  stdout.write = (chunk, ...rest) => (mute.muted ? true : write(chunk, ...rest));
  const question = rl.question('  paste your 80085 API key: ');
  mute.muted = true;
  try {
    return (await question).trim();
  } finally {
    mute.muted = false;
    stdout.write = write;
    write('\n');
  }
}

async function main(argv) {
  const args = parseArgs(argv);
  if (args.help) return console.log(HELP), 0;

  const apiUrl = (args.apiUrl || process.env.BOOBS_API_URL || DEFAULT_API).replace(/\/+$/, '');
  console.log(`\n  \x1b[7m 80085 \x1b[0m  the shared brain for AI agents\n`);

  // --- find the configs -------------------------------------------------
  const found = args.target
    ? [{ name: 'chosen', path: args.target }]
    : targets().filter((t) => existsSync(t.path));

  if (!found.length) {
    const fallback = join(process.cwd(), '.mcp.json');
    console.log(bad('no agent config found in the usual places.'));
    console.log(dim(`    will create ${fallback} instead.\n`));
    found.push({ name: 'this project', path: fallback });
  }
  for (const t of found) console.log(ok(`found ${t.name.padEnd(16)} ${dim(t.path)}`));

  // --- choose ------------------------------------------------------------
  const rl = createInterface({ input: stdin, output: stdout });
  let chosen = found;
  let key = '';
  try {
    if (found.length > 1 && !args.all && stdin.isTTY) {
      console.log('');
      found.forEach((t, i) => console.log(`    ${i + 1}) ${t.name}`));
      const pick = (await rl.question('\n  which? (number, or "a" for all) ')).trim().toLowerCase();
      if (pick !== 'a' && pick !== '') {
        const i = Number(pick) - 1;
        if (!Number.isInteger(i) || !found[i]) {
          console.log(bad('not one of the options.'));
          return 1;
        }
        chosen = [found[i]];
      }
    }

    // --- key -------------------------------------------------------------
    key = args.key || process.env.BOOBS_API_KEY || '';
    if (!key) {
      if (!stdin.isTTY) {
        console.log(bad('no key. pass --key sk_80085_... or set BOOBS_API_KEY.'));
        return 1;
      }
      console.log(dim('\n  Nothing is minted for you — paste a key you already have.'));
      console.log(dim('  No key yet? https://80085.ai/key\n'));
      key = await askKey(rl);
    }
    if (!key.startsWith(KEY_PREFIX)) {
      console.log(bad(`that does not look like a key — they start with ${KEY_PREFIX}`));
      return 1;
    }
  } finally {
    rl.close();
  }

  return await apply(chosen, key, apiUrl, args);
}

async function apply(chosen, key, apiUrl, args) {
  const block = serverBlock(key, apiUrl);
  console.log('');

  for (const t of chosen) {
    const current = read(t.path);
    if (current === undefined) {
      console.log(bad(`${t.path} is not valid JSON — refusing to touch it.`));
      return 1;
    }

    const next = mergeConfig(current, block);
    if (args.dryRun) {
      console.log(ok(`would write ${t.path}`));
      console.log(dim(JSON.stringify({ mcpServers: { 80085: block } }, null, 2)));
      continue;
    }

    if (current !== null) {
      // Timestamped so a second run never destroys the first backup.
      const backup = `${t.path}.bak-${Date.now()}`;
      copyFileSync(t.path, backup);
      console.log(ok(`backed up   ${dim(backup)}`));
    } else {
      mkdirSync(dirname(t.path), { recursive: true });
    }

    writeFileSync(t.path, JSON.stringify(next, null, 2) + '\n');
    console.log(ok(`wrote       ${dim(t.path)}`));
  }

  console.log(dim('\n  the block written:\n'));
  console.log(
    dim(
      JSON.stringify({ mcpServers: { 80085: { ...block, env: { ...block.env, BOOBS_API_KEY: `${KEY_PREFIX}…` } } } }, null, 2)
        .split('\n')
        .map((l) => '    ' + l)
        .join('\n')
    )
  );

  // --- verify ------------------------------------------------------------
  console.log('');
  try {
    const res = await fetch(`${apiUrl}/v1/health`, { signal: AbortSignal.timeout(10000) });
    const body = await res.text();
    if (res.ok) console.log(ok(`verified    ${dim(`${apiUrl}/v1/health → ${body.trim()}`)}`));
    else console.log(bad(`${apiUrl}/v1/health → ${res.status}`));
  } catch {
    console.log(bad(`could not reach ${apiUrl} — the config is written, the API is not answering.`));
  }

  console.log(`\n  \x1b[1mRestart your agent.\x1b[0m There is no step three.\n`);
  console.log(dim('  Then add this to its system prompt:'));
  console.log(
    dim('    "Before solving a non-trivial task from scratch, call recall_experience')
  );
  console.log(dim('     to check whether a verified executable solution already exists."\n'));
  return 0;
}

// Only run when invoked as a command, so the helpers stay importable by tests.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).then((code) => process.exit(code ?? 0));
}
