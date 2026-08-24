/**
 * Every page the copy refers to is a link, and the key is minted where the
 * install is. Reads the built public/, like negotiate.test.js does.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const pub = join(dirname(fileURLToPath(import.meta.url)), 'public');
const home = readFileSync(join(pub, 'p', 'home.html'), 'utf8');
const key = readFileSync(join(pub, 'key.html'), 'utf8');

const hrefs = (html) => [...html.matchAll(/<a href="([^"]+)" target="_blank"/g)].map((m) => m[1]);

test('every page the homepage mentions is clickable, in a new tab', () => {
  const links = hrefs(home);
  for (const p of ['/llms.txt', '/llms-full.txt', '/agents.md', '/TERMS.md', '/.well-known/mcp.json']) {
    assert.ok(links.includes(p), `${p} is mentioned but not linked`);
  }
  assert.ok(links.includes('https://80085.ai/prompt.txt'), 'the curl lines link too');
});

test('what a browser cannot open is not a link', () => {
  const links = hrefs(home);
  assert.ok(!links.some((h) => h.includes('mcp.80085.ai')), 'an MCP endpoint answers a browser with 406');
  assert.ok(!home.includes('href="/markdown"'), 'text/markdown is a media type, not a page');
  assert.ok(!home.includes('href="/ 0"'));
});

test('a key is minted on the homepage, not on some other page', () => {
  // Twice: the install block is shared by both flip states, so nothing here
  // may rely on an id.
  assert.equal((home.match(/class="mintbox"/g) || []).length, 2);
  assert.ok(!/id="mint"/.test(home), 'ids would collide across the two states');
  assert.ok(home.includes('<script type="module" src="/key.js">'));
});

test('every install block gains the key once it exists', () => {
  const keyed = (html) => [...html.matchAll(/data-keyed="([^"]+)"/g)].map((m) => m[1]);
  for (const t of keyed(home)) assert.ok(t.includes('{KEY}'), t);
  // Both the one command and the config, on both pages.
  assert.ok(keyed(home).some((t) => t.startsWith('claude mcp add') && t.includes('--header')));
  assert.ok(keyed(key).some((t) => t.startsWith('claude mcp add')));
  assert.ok(keyed(key).some((t) => t.includes('mcpServers')));
});
