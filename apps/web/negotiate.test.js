/**
 * Content negotiation is done by vercel.json rewrites rather than by code, so
 * this tests the rules themselves: it reads vercel.json and resolves requests
 * through it the way Vercel documents — first match wins, every `has`
 * condition on a rule must hold, header values are regexes.
 *
 * It cannot prove Vercel's matcher behaves identically, but it does catch the
 * two things that actually go wrong in a rules table: a regex that does not
 * match what you thought, and rules in the wrong order. WEDSITE_DESIGN.md
 * section 18 calls a cross-served representation the most likely production
 * bug in the whole build.
 */

import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const { rewrites } = JSON.parse(
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'vercel.json'), 'utf8')
);

/** Resolve a request to the path Vercel would serve. */
function resolve(pathname, { headers = {}, query = {} } = {}) {
  for (const rule of rewrites) {
    if (rule.source !== pathname) continue;
    const conditions = rule.has ?? [];
    const holds = conditions.every((c) => {
      const actual = c.type === 'header' ? headers[c.key.toLowerCase()] : query[c.key];
      if (actual === undefined) return false;
      return new RegExp(`^(?:${c.value})$`).test(actual);
    });
    if (holds) return rule.destination;
  }
  return pathname; // no rule matched
}

const CHROME =
  'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8';

test('a browser gets HTML', () => {
  assert.equal(
    resolve('/', {
      headers: { accept: CHROME, 'user-agent': 'Mozilla/5.0 (Windows NT 10.0) Chrome/141' }
    }),
    '/p/home'
  );
});

test('curl gets the ANSI response', () => {
  assert.equal(
    resolve('/', { headers: { 'user-agent': 'curl/8.4.0', accept: '*/*' } }),
    '/index.ansi'
  );
  assert.equal(
    resolve('/install', { headers: { 'user-agent': 'curl/8.4.0', accept: '*/*' } }),
    '/install.ansi'
  );
});

test('wget and httpie get it too', () => {
  for (const ua of ['Wget/1.21.4', 'HTTPie/3.2.2']) {
    assert.equal(resolve('/', { headers: { 'user-agent': ua, accept: '*/*' } }), '/index.ansi');
  }
});

test('every AI crawler in the spec gets markdown', () => {
  const bots = [
    'ClaudeBot/1.0',
    'Claude-User/1.0',
    'Claude-SearchBot/1.0',
    'GPTBot/1.2',
    'ChatGPT-User/1.0',
    'OAI-SearchBot/1.0',
    'PerplexityBot/1.0',
    'Perplexity-User/1.0',
    'Google-Extended',
    'Bytespider',
    'CCBot/2.0',
    'Applebot-Extended',
    'cohere-ai',
    'Meta-ExternalAgent/1.0'
  ];
  for (const ua of bots) {
    assert.equal(
      resolve('/', { headers: { 'user-agent': ua, accept: CHROME } }),
      '/index.md',
      `${ua} did not get markdown`
    );
  }
});

test('a crawler sending a browser Accept still gets markdown', () => {
  // The UA rules sit above the Accept rules on purpose: a crawler that
  // advertises text/html must not be handed the HTML page.
  assert.equal(
    resolve('/', { headers: { 'user-agent': 'ClaudeBot/1.0', accept: CHROME } }),
    '/index.md'
  );
});

test('Accept: text/markdown gets markdown', () => {
  assert.equal(resolve('/', { headers: { accept: 'text/markdown' } }), '/index.md');
});

test('Accept: text/plain gets plain text', () => {
  assert.equal(resolve('/', { headers: { accept: 'text/plain' } }), '/index.txt');
});

test('?format overrides everything, including a browser', () => {
  assert.equal(
    resolve('/', { headers: { accept: CHROME, 'user-agent': 'Chrome' }, query: { format: 'md' } }),
    '/index.md'
  );
  assert.equal(
    resolve('/', { headers: { accept: CHROME }, query: { format: 'txt' } }),
    '/index.txt'
  );
  // Terminal mode fetches this exact URL.
  assert.equal(resolve('/install', { query: { format: 'txt' } }), '/install.txt');
});

test('a request with no Accept and no known UA still gets a page', () => {
  assert.equal(resolve('/', {}), '/p/home');
});

test('the HTML pages sit where the filesystem will not claim them first', () => {
  // The production bug this file failed to catch the first time: Vercel
  // applies rewrites ONLY when no filesystem route already answers the
  // request, so a public/index.html answers "/" before any rule runs and
  // `curl 80085.ai` returns HTML. Serving the page from a path no request
  // names keeps "/" and "/install" unclaimed.
  for (const claimed of ['/index.html', '/install.html']) {
    assert.ok(
      !existsSync(join(dirname(fileURLToPath(import.meta.url)), 'public', claimed)),
      `${claimed} exists and will pre-empt every negotiation rule`
    );
  }
  assert.equal(resolve('/', { headers: { accept: CHROME } }), '/p/home');
  assert.equal(resolve('/install', { headers: { accept: CHROME } }), '/p/install');
});

test('/58008 serves the page, which flips itself from the path', () => {
  assert.equal(resolve('/58008', { headers: { accept: CHROME } }), '/p/home');
});

test('openapi.json is proxied to the live API rather than duplicated', () => {
  assert.equal(resolve('/openapi.json'), 'https://api.80085.ai/openapi.json');
});

test('every rewrite destination that is local actually exists', () => {
  // cleanUrls: true means a destination is written without its .html, because
  // naming the .html file makes Vercel 308 to the extensionless form instead
  // of serving it. Resolve both spellings when checking the build output.
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rule of rewrites) {
    if (rule.destination.startsWith('http')) continue;
    const base = join(here, 'public', rule.destination);
    assert.ok(
      existsSync(base) || existsSync(`${base}.html`),
      `${rule.destination} is not produced by build.mjs`
    );
  }
});

test('no rewrite names a .html file, which cleanUrls would redirect', () => {
  for (const rule of rewrites) {
    assert.ok(
      !rule.destination.endsWith('.html'),
      `${rule.destination} will 308 to its extensionless form rather than serve`
    );
  }
});
