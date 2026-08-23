/**
 * The corpus size on the site is a fact about the manifest, not a number.
 *
 * It was typed twice — once in content.js, once in build.mjs — and by the time
 * anyone checked, the page said 21, /llms.txt said 24, and the manifest
 * defined 30. Every one of those was published simultaneously, and content.js's
 * own header explains why that could not happen.
 *
 * So this asserts the property rather than the number: whatever the manifest
 * defines, every rendered surface says the same thing.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import assert from 'node:assert/strict';

import { CORPUS } from './content.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const MANIFEST = join(HERE, '..', '..', 'capabilities', 'manifest.json');

test('CORPUS is read from the manifest, not typed', () => {
  const defined = Object.keys(
    JSON.parse(readFileSync(MANIFEST, 'utf8')).capabilities
  ).length;
  assert.equal(CORPUS, defined);
  assert.ok(CORPUS > 0, 'a corpus of nothing means the manifest was not read');
});

test('every rendered surface agrees with the manifest', () => {
  const out = join(HERE, 'public');
  const surfaces = ['home.md', 'llms.txt', 'llms-full.txt', 'p/home.html'];

  let checked = 0;
  for (const name of surfaces) {
    let body;
    try {
      body = readFileSync(join(out, name), 'utf8');
    } catch {
      continue; // public/ is build output; skip when the site has not been built
    }

    // Any "<n>-capability" or "defines <n> capabilities" claim must be the
    // real count. A wrong number is worse than no number, because it reads as
    // deliberate.
    for (const match of body.matchAll(/(\d+)[- ]capabilit/gi)) {
      assert.equal(
        Number(match[1]),
        CORPUS,
        `${name} claims ${match[1]} capabilities; the manifest defines ${CORPUS}`
      );
      checked += 1;
    }
  }

  assert.ok(
    checked > 0,
    'no surface mentioned the corpus size — run `node build.mjs` first, or the claim was dropped'
  );
});
