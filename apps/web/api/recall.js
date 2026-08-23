/**
 * Read-only recall proxy for terminal mode.
 *
 * A stranger can query the product from the homepage with no key and no
 * signup, which is the most convincing thing the site can do. That makes it
 * the site's only write path to the outside world, so it is deliberately
 * boring: one endpoint, read-only credentials, hard rate limit, no logging of
 * what anyone asked.
 *
 * RECALL_PUBLIC_KEY must hold `experiences:read` and nothing else. It cannot
 * execute, record, or verify — that is enforced by the key's scopes on the
 * API, not by this file.
 */

export const config = { runtime: 'edge' };

const API = process.env.API_URL || 'https://api.80085.ai';
const LIMIT = 10; // requests
const WINDOW = 60_000; // per minute, per IP

/* ponytail: in-memory counters, so the limit is per edge instance rather than
 * global. Good enough for a demo endpoint on a marketing page; move to Redis
 * (the API already runs one) if this ever becomes a real surface. */
const hits = new Map();

function allowed(ip) {
  const now = Date.now();
  const seen = (hits.get(ip) || []).filter((t) => now - t < WINDOW);
  if (seen.length >= LIMIT) return false;
  seen.push(now);
  hits.set(ip, seen);
  if (hits.size > 5000) hits.clear(); // crude, bounded, fine
  return true;
}

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' }
  });

export default async function handler(req) {
  if (req.method !== 'POST') return json({ detail: 'POST only' }, 405);

  const key = process.env.RECALL_PUBLIC_KEY;
  if (!key) return json({ detail: 'live recall is not wired up yet' }, 503);

  const ip = req.headers.get('x-forwarded-for')?.split(',')[0].trim() || 'anon';
  if (!allowed(ip)) return json({ detail: 'slow down — 10 queries a minute' }, 429);

  let task;
  try {
    ({ task } = await req.json());
  } catch {
    return json({ detail: 'expected {"task": "..."}' }, 400);
  }
  // Bounds match the API's own RecallRequest so a bad query fails here rather
  // than burning a round trip to be rejected there.
  if (typeof task !== 'string' || task.trim().length < 3) {
    return json({ detail: 'task must be at least 3 characters' }, 400);
  }
  if (task.length > 500) return json({ detail: 'task is too long' }, 400);

  // The query itself is never logged — only that one happened.
  console.log('recall');

  try {
    const res = await fetch(`${API}/v1/experiences/recall`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
      body: JSON.stringify({
        task: task.trim(),
        context: {},
        constraints: {},
        limit: 3
      })
    });
    if (!res.ok) return json({ detail: `recall returned ${res.status}` }, 502);
    const data = await res.json();
    return new Response(JSON.stringify({ matches: data.matches ?? [] }), {
      headers: {
        'content-type': 'application/json',
        'cache-control': 'public, max-age=30'
      }
    });
  } catch {
    return json({ detail: 'recall is unreachable right now' }, 502);
  }
}
