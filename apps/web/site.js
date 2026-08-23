/**
 * Everything the page does once JavaScript arrives.
 *
 * The page is complete without this file: the copy is server-rendered and the
 * install is completable with JS disabled. This adds the calculator, the flip,
 * the boot self-test, and the terminal — all of which are delight, none of
 * which are load-bearing.
 */

import { BRAND, initial, press } from './calc.js';
import { readout } from './seg.js';
import { terminal } from './terminal.js';

const $ = (sel) => document.querySelector(sel);
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ theme --

const themeBtn = $('#theme');
themeBtn?.addEventListener('click', () => {
  const root = document.documentElement;
  // Whatever is on screen right now, go to the other one — whether we got here
  // from the system preference or from an earlier explicit choice.
  const dark = getComputedStyle(root).getPropertyValue('--paper').trim().startsWith('#00');
  const next = dark ? 'light' : 'dark';
  root.dataset.theme = next;
  try {
    localStorage.setItem('theme', next);
  } catch {
    /* private mode: the choice just doesn't outlive the tab */
  }
});

// ------------------------------------------------------------------- copy --

for (const btn of document.querySelectorAll('.copy[data-copy]')) {
  btn.addEventListener('click', () => {
    const text = btn.dataset.copy;
    const ok = () => {
      btn.textContent = '✅';
      setTimeout(() => (btn.textContent = '📋'), 1200);
    };
    const fallback = () => {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.append(ta);
      ta.select();
      try {
        document.execCommand('copy');
        ok();
      } finally {
        ta.remove();
      }
    };
    // Nothing is awaited before the write: iOS Safari only honours a clipboard
    // write that happens inside the user-gesture task itself.
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(ok, fallback);
    else fallback();
  });
}

// ------------------------------------------------------------------ sound --

let sound = false;
try {
  sound = localStorage.getItem('sound') === '1';
} catch {
  /* ignore */
}
const soundBtn = $('#sound');
const paintSound = () => soundBtn && (soundBtn.textContent = sound ? '🔊' : '🔇');
paintSound();
soundBtn?.addEventListener('click', () => {
  sound = !sound;
  try {
    localStorage.setItem('sound', sound ? '1' : '0');
  } catch {
    /* ignore */
  }
  paintSound();
  blip();
});

let audio;
function blip() {
  if (!sound) return;
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = 'square';
    osc.frequency.value = 880;
    gain.gain.value = 0.03;
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.012);
  } catch {
    /* no audio, no problem */
  }
}

// ------------------------------------------------------------- calculator --

const view = $('#readout');
const found = $('#found');
let state = initial();
let idle;

function paint(value = state.display) {
  view.innerHTML = readout(value);
  view.setAttribute('aria-label', `display shows ${value}`);
}

function flash() {
  if (reduced.matches) return;
  view.classList.add('flash');
  setTimeout(() => view.classList.remove('flash'), 200);
}

function say(text) {
  found.textContent = text;
  found.hidden = !text;
}

function restIdle() {
  clearTimeout(idle);
  // The site's resting state is always the brand.
  idle = setTimeout(() => {
    state = initial();
    paint();
  }, 30000);
}

function key(k, viaEquals = false) {
  blip();
  restIdle();
  const before = state.display;
  state = press(state, k);
  paint();

  if (state.display === BRAND && before !== BRAND) {
    flash();
    // Getting there by arithmetic is a different achievement from typing it.
    if (viaEquals) say("✅ you found it the hard way. that's the whole product.");
  } else if (state.display === '58008') {
    flip();
  } else if (state.display === '1337') {
    say('> nice. see /1337');
  } else if (k === 'C' || k === 'brand') {
    say('');
  }
}

// Pointer input. Long-pressing C resets to the brand rather than to zero.
let held;
for (const btn of document.querySelectorAll('.keys button')) {
  const k = btn.dataset.key;
  if (k === 'flip') {
    btn.addEventListener('click', () => flip());
    continue;
  }
  btn.addEventListener('click', () => key(k, k === '='));
  if (k === 'C') {
    const start = () => (held = setTimeout(() => key('brand'), 600));
    const stop = () => clearTimeout(held);
    btn.addEventListener('pointerdown', start);
    for (const e of ['pointerup', 'pointerleave', 'pointercancel']) {
      btn.addEventListener(e, stop);
    }
  }
}

// Keyboard. The calculator must be fully operable without a mouse.
const KEYS = {
  Enter: '=',
  '=': '=',
  Escape: 'C',
  Backspace: 'back',
  Delete: 'C',
  x: '*',
  X: '*'
};
addEventListener('keydown', (e) => {
  if (termOpen || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  if (e.key === '`' || e.key === '~') {
    e.preventDefault();
    return openTerm();
  }
  if (e.key === 'f' || e.key === 'F') {
    e.preventDefault();
    return flip();
  }

  const k = KEYS[e.key] ?? ('0123456789.+-*/%'.includes(e.key) ? e.key : null);
  if (!k) return;
  e.preventDefault();
  key(k, k === '=');
});

// -------------------------------------------------------------- the flip ---

const states = { serious: $('#serious'), stupid: $('#stupid') };
let flipped = false;
let flipping = false;

function swap() {
  flipped = !flipped;
  const on = flipped ? 'stupid' : 'serious';
  const off = flipped ? 'serious' : 'stupid';
  states[on].dataset.state = 'shown';
  states[on].removeAttribute('aria-hidden');
  states[off].dataset.state = 'hidden';
  states[off].setAttribute('aria-hidden', 'true');

  state = { ...initial(), display: flipped ? '58008' : BRAND };
  paint();
  say('');

  const url = new URL(location.href);
  if (flipped) url.searchParams.set('flip', '1');
  else url.searchParams.delete('flip');
  history.replaceState(null, '', url);
  try {
    // sessionStorage, not localStorage: a returning visitor gets SERIOUS first.
    sessionStorage.setItem('flip', flipped ? '1' : '0');
  } catch {
    /* ignore */
  }
}

async function flip() {
  if (flipping) return;
  flipping = true;
  const stage = $('.stage');

  if (reduced.matches) {
    swap();
    flipping = false;
    return;
  }

  stage.style.transition = 'transform 600ms cubic-bezier(.8,0,.2,1)';
  stage.style.transform = 'rotate(180deg)';
  // Swap at exactly halfway, while the text is vertical and unreadable, then
  // snap the rotation back to zero with transitions off. The reader perceives
  // one continuous rotation; the DOM never ends up upside down.
  await wait(300);
  swap();
  stage.style.transition = 'none';
  stage.style.transform = 'rotate(0deg)';
  await wait(300);
  stage.style.transition = '';
  flipping = false;
}

for (const btn of document.querySelectorAll('.flip')) {
  btn.addEventListener('click', () => flip());
}

// -------------------------------------------------------------- terminal ---

const term = $('#term');
const termOut = $('#term-out');
const termIn = $('#term-in');
const history_ = [];
let histAt = 0;
let termOpen = false;

const NAMES = ['help', 'install', 'recall', 'whoami', 'flip', 'exit', 'clear', ...Object.keys(terminal.commands)];

function echo(text) {
  termOut.textContent += text + '\n';
  term.scrollTop = term.scrollHeight;
}

function openTerm() {
  termOpen = true;
  term.hidden = false;
  if (!termOut.textContent) echo(terminal.motd + '\n');
  termIn.focus();
}

function closeTerm() {
  termOpen = false;
  term.hidden = true;
}

async function run(line) {
  const [cmd, ...rest] = line.trim().split(/\s+/);
  const arg = rest.join(' ');
  if (!cmd) return;

  if (line.trim() in terminal.commands) return echo(terminal.commands[line.trim()]);
  if (cmd in terminal.commands) return echo(terminal.commands[cmd]);

  switch (cmd) {
    case 'help':
      return echo(terminal.help);
    case 'clear':
      termOut.textContent = '';
      return;
    case 'exit':
      return closeTerm();
    case 'flip':
      closeTerm();
      return flip();
    case 'install':
      return echo(await (await fetch('/install?format=txt')).text());
    case 'recall': {
      if (!arg) return echo('usage: recall <task in your own words>');
      echo('...');
      try {
        const res = await fetch('/api/recall', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ task: arg })
        });
        const data = await res.json();
        if (!res.ok) return echo(data.detail || `error ${res.status}`);
        if (!data.matches?.length) {
          return echo(
            'no verified Experience matches that yet.\n' +
              'an empty answer is a correct answer — relevance is not evidence.'
          );
        }
        for (const m of data.matches) {
          const pct = typeof m.confidence === 'number' ? (m.confidence * 100).toFixed(1) + '%' : '—';
          echo(
            `  [${m.recommendation ?? '?'}] ${m.goal ?? m.experience_id}\n` +
              `      confidence ${pct}  verified runs ${m.successful_runs ?? 0}`
          );
        }
      } catch {
        echo('recall is unreachable right now.');
      }
      return;
    }
    default:
      return echo(`${cmd}: command not found. try \`help\`.`);
  }
}

termIn?.addEventListener('keydown', async (e) => {
  if (e.key === 'Enter') {
    const line = termIn.value;
    echo(`80085:~$ ${line}`);
    termIn.value = '';
    if (line.trim()) {
      history_.push(line);
      histAt = history_.length;
    }
    await run(line);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (histAt > 0) termIn.value = history_[--histAt] ?? '';
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    histAt = Math.min(histAt + 1, history_.length);
    termIn.value = history_[histAt] ?? '';
  } else if (e.key === 'Tab') {
    e.preventDefault();
    const hit = NAMES.find((n) => n.startsWith(termIn.value));
    if (hit) termIn.value = hit;
  } else if (e.key === 'Escape') {
    closeTerm();
  }
});

// ------------------------------------------------------------------ boot ---

async function boot() {
  // Segment self-test, exactly like real hardware. Once per session, and never
  // for a reader who has asked for less motion.
  view.removeAttribute('aria-live');
  let skip = false;
  const bail = () => (skip = true);
  for (const e of ['keydown', 'pointerdown', 'wheel']) {
    addEventListener(e, bail, { once: true, passive: true });
  }

  paint('888888888');
  await wait(400);
  if (!skip) {
    paint('');
    await wait(300);
  }
  for (let i = 1; i <= BRAND.length && !skip; i++) {
    paint(BRAND.slice(0, i));
    await wait(90);
  }
  paint(BRAND);
  view.setAttribute('aria-live', 'polite');
  document.body.classList.add('ready');
}

const shouldBoot = (() => {
  try {
    if (sessionStorage.getItem('booted')) return false;
    sessionStorage.setItem('booted', '1');
    return true;
  } catch {
    return true;
  }
})();

// /58008 is the shareable link: it lands you on the stupid side directly.
if (new URLSearchParams(location.search).get('flip') === '1' || location.pathname === '/58008') {
  swap();
}
else {
  try {
    if (sessionStorage.getItem('flip') === '1') swap();
  } catch {
    /* ignore */
  }
}

if (shouldBoot && !reduced.matches) boot();
else {
  paint();
  document.body.classList.add('ready');
}

restIdle();
