import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DEFAULT_API, mergeConfig, serverBlock, targets } from './init.js';

test('the server block is digest-agnostic but repo-pinned and installable', () => {
  const b = serverBlock('sk_80085_abc');
  assert.equal(b.command, 'uvx');
  assert.ok(b.args.some((a) => a.includes('subdirectory=apps/mcp')));
  assert.equal(b.args.at(-1), '80085-mcp');
  assert.equal(b.env.BOOBS_API_URL, DEFAULT_API);
  assert.equal(b.env.BOOBS_API_KEY, 'sk_80085_abc');
});

test('merging preserves everything already in the config', () => {
  const existing = {
    mcpServers: { other: { command: 'node' } },
    somethingElse: { keep: true }
  };
  const next = mergeConfig(existing, serverBlock('sk_80085_x'));
  assert.deepEqual(next.somethingElse, { keep: true });
  assert.deepEqual(next.mcpServers.other, { command: 'node' });
  assert.equal(next.mcpServers['80085'].command, 'uvx');
});

test('merging into nothing produces a valid config', () => {
  const next = mergeConfig(null, serverBlock('sk_80085_x'));
  assert.equal(Object.keys(next.mcpServers).length, 1);
});

test('re-running replaces our block rather than duplicating it', () => {
  let cfg = mergeConfig(null, serverBlock('sk_80085_old'));
  cfg = mergeConfig(cfg, serverBlock('sk_80085_new'));
  assert.equal(Object.keys(cfg.mcpServers).length, 1);
  assert.equal(cfg.mcpServers['80085'].env.BOOBS_API_KEY, 'sk_80085_new');
});

test('the merge never mutates the config it was given', () => {
  const existing = { mcpServers: { other: {} } };
  const copy = JSON.parse(JSON.stringify(existing));
  mergeConfig(existing, serverBlock('sk_80085_x'));
  assert.deepEqual(existing, copy);
});

test('each platform gets the right Claude Desktop path', () => {
  const win = targets('win32', { APPDATA: 'C:\\Users\\x\\AppData\\Roaming' }, 'C:\\Users\\x');
  assert.ok(win.find((t) => t.name === 'Claude Desktop').path.includes('AppData'));

  const mac = targets('darwin', {}, '/Users/x');
  assert.ok(
    mac.find((t) => t.name === 'Claude Desktop').path.includes('Application Support')
  );

  const linux = targets('linux', {}, '/home/x');
  assert.ok(linux.find((t) => t.name === 'Claude Desktop').path.includes('.config'));
});

test('every supported client is covered', () => {
  const names = targets('linux', {}, '/home/x').map((t) => t.name);
  for (const n of ['Claude Code', 'Claude Desktop', 'Cursor', 'Windsurf', 'this project']) {
    assert.ok(names.includes(n), `missing ${n}`);
  }
});
