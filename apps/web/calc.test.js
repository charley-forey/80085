import assert from 'node:assert/strict';
import { test } from 'node:test';

import { BRAND, fmt, initial, press } from './calc.js';
import { SEG, readout } from './seg.js';

/** Type a sequence of keys and return the resulting display. */
const type = (...keys) => keys.reduce(press, initial()).display;

test('resting state is the brand', () => {
  assert.equal(initial().display, BRAND);
});

test('2 + 2 = 4', () => {
  assert.equal(type('2', '+', '2', '='), '4');
});

test('divide by zero shows Error', () => {
  assert.equal(type('8', '/', '0', '='), 'Error');
});

test('Error is sticky until C', () => {
  const errored = ['8', '/', '0', '='].reduce(press, initial());
  assert.equal(press(errored, '5').display, 'Error');
  assert.equal(press(errored, '+').display, 'Error');
  assert.equal(press(errored, 'C').display, '0');
});

test('long-press reset returns to the brand', () => {
  const errored = ['8', '/', '0', '='].reduce(press, initial());
  assert.equal(press(errored, 'brand').display, BRAND);
});

test('display caps at nine digits', () => {
  assert.equal(type(...'1234567890123'.split('')), '123456789');
});

test('repeated = repeats the operation', () => {
  const keys = ['2', '+', '3', '='];
  let s = keys.reduce(press, initial());
  assert.equal(s.display, '5');
  s = press(s, '=');
  assert.equal(s.display, '8');
  s = press(s, '=');
  assert.equal(s.display, '11');
});

test('a decimal point cannot be entered twice', () => {
  assert.equal(type('1', '.', '5', '.', '2'), '1.52');
});

test('a bare decimal point opens with a leading zero', () => {
  assert.equal(type('.', '5'), '0.5');
});

test('leading zeros are replaced, not appended', () => {
  assert.equal(type('0', '0', '7'), '7');
});

test('0.1 + 0.2 displays 0.3, not float noise', () => {
  assert.equal(type('.', '1', '+', '.', '2', '='), '0.3');
});

test('precision shrinks to fit the nine cells', () => {
  // 1/3 at nine significant figures would need ten cells.
  assert.equal(type('1', '/', '3', '='), '0.33333333');
});

test('chaining resolves the pending operation', () => {
  assert.equal(type('2', '+', '3', '+', '4', '='), '9');
});

test('backspace deletes, and never leaves an empty display', () => {
  assert.equal(type('1', '2', '3', 'back'), '12');
  assert.equal(type('7', 'back'), '0');
});

test('percent divides by a hundred', () => {
  assert.equal(type('5', '0', '%'), '0.5');
});

test('overflow falls back to exponent notation that still fits', () => {
  const out = fmt(1.23456789e15);
  assert.ok(out.includes('E'), `expected exponent form, got ${out}`);
  assert.ok(out.replace(/\./g, '').length <= 9, `too wide: ${out}`);
});

test('negative results keep their sign', () => {
  assert.equal(type('3', '-', '5', '='), '-2');
});

// --- the readout ---------------------------------------------------------

test('every character the calculator can display has a glyph', () => {
  for (const ch of [...'0123456789.-', ...'Error']) {
    if (ch === '.') continue; // the decimal point is a segment, not a cell
    assert.ok(ch in SEG, `no seven-segment glyph for ${JSON.stringify(ch)}`);
  }
});

test('the readout is always exactly nine cells wide', () => {
  const count = (v) => (readout(v).match(/<svg/g) || []).length;
  assert.equal(count('0'), 9);
  assert.equal(count(BRAND), 9);
  assert.equal(count('Error'), 9);
  assert.equal(count('123456789'), 9);
});

test('a decimal point shares a cell with the digit before it', () => {
  // "0.5" is two cells of content, so it pads to nine like anything else.
  assert.equal((readout('0.5').match(/<svg/g) || []).length, 9);
});
