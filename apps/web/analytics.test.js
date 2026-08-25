/**
 * The GA4 tag is spread across three files that can drift independently: the
 * loader `<script>` in every page <head> (build.mjs), the `gtag('config',...)`
 * call in boot.js (also build.mjs, but a separate literal), and the CSP in
 * vercel.json that decides whether the browser is allowed to run either of
 * them. Get any one of them wrong and the site still builds, still deploys and
 * still looks correct -- it just silently records nothing, which is the one
 * analytics failure nobody notices until a month of data is missing.
 *
 * So this asserts the whole chain against the built public/, the way
 * seo.test.js and negotiate.test.js do.
 */

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const pub = join(HERE, 'public');

/** The one place the ID is asserted. Keep in step with GA_ID in build.mjs. */
const GA_ID = 'G-KBY6VGNJK8';

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

const html = pages().map((file) => [file, readFileSync(join(pub, file), 'utf8')]);
const boot = readFileSync(join(pub, 'boot.js'), 'utf8');
const { headers } = JSON.parse(readFileSync(join(HERE, 'vercel.json'), 'utf8'));

test('the build produced pages to check', () => {
  assert.ok(html.length > 0, 'no HTML in public/ -- run `node build.mjs` first');
});

test('every page loads the gtag.js tag for the right property', () => {
  for (const [file, body] of html) {
    assert.ok(
      body.includes(`<script async src="https://www.googletagmanager.com/gtag/js?id=${GA_ID}"></script>`),
      `${file}: no gtag.js loader for ${GA_ID}`
    );
  }
});

test('every page loads boot.js, which is what calls gtag config', () => {
  for (const [file, body] of html) {
    assert.ok(body.includes('<script src="/boot.js"></script>'), `${file}: does not load boot.js`);
  }
});

test('no page still points at a different measurement ID', () => {
  for (const [file, body] of [...html, ['boot.js', boot]]) {
    const ids = new Set([...body.matchAll(/\bG-[A-Z0-9]{6,}\b/g)].map((m) => m[0]));
    assert.deepEqual([...ids], [GA_ID], `${file}: unexpected measurement IDs`);
  }
});

test('boot.js defines the dataLayer queue before configuring', () => {
  // The loader is async, so the stub has to exist synchronously or the config
  // call throws and the first pageview is lost.
  assert.match(boot, /window\.dataLayer\s*=\s*window\.dataLayer\s*\|\|\s*\[\]/);
  assert.match(boot, /function gtag\(\)\s*\{\s*dataLayer\.push\(arguments\)\s*\}/);
  const stub = boot.indexOf('window.dataLayer');
  const config = boot.indexOf("gtag('config'");
  assert.ok(config > stub, 'boot.js configures gtag before defining it');
});

test('boot.js sends the pageview for the right property', () => {
  assert.match(boot, /gtag\('js',\s*new Date\(\)\)/);
  assert.ok(boot.includes(`gtag('config','${GA_ID}')`), `boot.js does not config ${GA_ID}`);
});

/** The `/(.*)` rule -- the one that applies to every response. */
const global = headers.find((h) => h.source === '/(.*)').headers;
const csp = global.find((h) => h.key === 'Content-Security-Policy').value;
const directive = (name) => csp.split(';').find((d) => d.trim().startsWith(`${name} `)) ?? '';

test('the CSP lets the tag load and report', () => {
  // Each of these is a source the tag actually uses; drop one and the browser
  // blocks it with nothing but a console error to say so.
  assert.ok(
    directive('script-src').includes('https://www.googletagmanager.com'),
    'script-src blocks gtag.js'
  );
  assert.ok(
    directive('connect-src').includes('https://www.google-analytics.com'),
    'connect-src blocks the collect beacon'
  );
  assert.ok(
    directive('img-src').includes('https://www.google-analytics.com'),
    'img-src blocks the pixel fallback'
  );
});

test('boot.js is not cached past a tag change', () => {
  const rule = headers.find((h) => h.source.includes('boot.js'));
  assert.ok(rule, 'boot.js has no Cache-Control rule, so it inherits the default');
  const cache = rule.headers.find((h) => h.key === 'Cache-Control').value;
  assert.match(cache, /must-revalidate/, 'a stale boot.js keeps reporting to the old property');
});
