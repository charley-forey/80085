/**
 * The copy exists in five places -- two HTML pages, the ANSI page, llms.txt,
 * agents.md -- plus prompt.txt and the social card, and rewriting the pages
 * has three times now left one of the others telling the old story. Nothing
 * caught it: every other test passed, the deploy was on the right commit, and
 * the stale words were found by a person looking at the site.
 *
 * So this asserts on the built output rather than on the source, and it names
 * the dead thesis rather than the live one -- a positive check would pass on a
 * page that says both.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

/** Wording from theses we abandoned. Any of it, anywhere, is a bug. */
const DEAD = [
  'shared brain',
  'second thoughts',
  'amnesia',
  'parse a stubborn csv',
  'call recall_experience'
];

const walk = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });

const TEXT = /\.(html|txt|md|svg|json|xml|ansi)$/;

test('no built surface carries copy from a dead thesis', () => {
  const offences = [];
  for (const path of walk('public').filter((p) => TEXT.test(p))) {
    const body = readFileSync(path, 'utf8').toLowerCase();
    for (const phrase of DEAD) if (body.includes(phrase)) offences.push(`${path}: "${phrase}"`);
  }
  assert.deepEqual(offences, [], `stale copy still served:\n  ${offences.join('\n  ')}`);
});

test('prompt.txt is the halt, because it is what we tell people to paste', () => {
  const prompt = readFileSync('public/prompt.txt', 'utf8');
  assert.match(prompt, /DO NOT GUESS/, 'prompt.txt no longer tells the agent to stop');
  assert.ok(prompt.length > 400, 'prompt.txt looks truncated');
});

test('every tool the MCP server exposes is named where agents read', () => {
  // An agent that never learns a tool exists never calls it. agents.md and
  // llms.txt are the two files they actually fetch.
  for (const file of ['public/agents.md', 'public/llms.txt']) {
    const body = readFileSync(file, 'utf8');
    for (const tool of ['should_i_ask', 'ask_for_help', 'recall_experience']) {
      assert.ok(body.includes(tool), `${file} never mentions ${tool}`);
    }
  }
});
