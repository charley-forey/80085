/**
 * The sitemap and the pages have to agree. They are generated from different
 * places in build.mjs, so nothing but a test stops them drifting apart, and
 * both ways of drifting are silent in production and loud in Search Console:
 * a page that canonicalises somewhere else drops out of the index, and a
 * sitemap that submits a noindex page earns "Submitted URL marked noindex".
 *
 * Reads the built public/, like negotiate.test.js does.
 */

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const pub = join(dirname(fileURLToPath(import.meta.url)), 'public');

/** Every generated .html, recursively, as paths relative to public/. */
function pages(dir = pub, prefix = '') {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory()
      ? pages(join(dir, e.name), `${prefix}${e.name}/`)
      : e.name.endsWith('.html')
        ? [prefix + e.name]
        : []
  );
}

const SITE = 'https://80085.ai';

const indexable = new Map();
for (const file of pages()) {
  const html = readFileSync(join(pub, file), 'utf8');
  const noindex = /<meta name="robots" content="noindex">/.test(html);
  const canonical = html.match(/<link rel="canonical" href="([^"]+)">/)?.[1];

  if (noindex) {
    assert.equal(canonical, undefined, `${file}: noindex page also declares a canonical`);
    continue;
  }
  assert.ok(canonical, `${file}: indexable page has no canonical`);
  assert.ok(canonical.startsWith(SITE), `${file}: canonical is off-site (${canonical})`);
  assert.ok(!indexable.has(canonical), `${file}: canonical ${canonical} is claimed twice`);
  indexable.set(canonical, file);
}

const sitemap = readFileSync(join(pub, 'sitemap.xml'), 'utf8');
const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);

test('sitemap lists exactly the indexable pages', () => {
  assert.deepEqual([...locs].sort(), [...indexable.keys()].sort());
});

test('every sitemap entry has a lastmod', () => {
  assert.equal(
    [...sitemap.matchAll(/<lastmod>\d{4}-\d{2}-\d{2}<\/lastmod>/g)].length,
    locs.length,
    'each <url> needs one ISO-date <lastmod>'
  );
});

test('indexable pages carry their own description and og:url', () => {
  const seen = new Set();
  for (const [canonical, file] of indexable) {
    const html = readFileSync(join(pub, file), 'utf8');
    const description = html.match(/<meta name="description" content="([^"]+)">/)?.[1];
    assert.ok(description, `${file}: no meta description`);
    assert.ok(!seen.has(description), `${file}: reuses another page's description verbatim`);
    seen.add(description);

    assert.ok(
      html.includes(`<meta property="og:url" content="${canonical}">`),
      `${file}: og:url disagrees with the canonical`
    );
  }
});
