/**
 * Minting a key, on the homepage and on /key. One handler for both.
 *
 * Press the button, get a key. It is shown once, kept in localStorage so a
 * return visit still has it, offered as a file, and written into every code
 * block on the page that has a {KEY} slot -- so the install command a visitor
 * copies next already carries it and nothing has to be pasted anywhere.
 *
 * The homepage carries the widget twice, once per flip state, so everything
 * here is by class and applies to every copy at once.
 *
 * Nothing is minted without a click: the API allows five an hour per address,
 * and a key nobody asked for is a credential nobody guards.
 */

const boxes = [...document.querySelectorAll('.mintbox')];
const STORE = '80085.key';

const stored = () => {
  try {
    return JSON.parse(localStorage.getItem(STORE) || 'null');
  } catch {
    return null;
  }
};

function show({ api_key: key, key_id: id }) {
  const api = boxes[0].dataset.api;
  const revoke = `curl -X POST -H "Authorization: Bearer ${key}" ${api}/v1/keys/${id}/revoke`;
  const file =
    'data:text/plain;charset=utf-8,' +
    encodeURIComponent(
      `80085 API key\n\n${key}\n\nkey_id: ${id}\n\nUse it:   Authorization: Bearer ${key}\n` +
        `Revoke:   ${revoke}\n\nThere is no account. This file is the recovery.\n`
    );

  for (const b of document.querySelectorAll('[data-keyed]')) {
    const text = b.dataset.keyed.replace(/\{KEY\}/g, key);
    b.dataset.copy = text;
    b.previousElementSibling.textContent = text;
  }
  for (const box of boxes) {
    const $ = (cls) => box.querySelector(`.${cls}`);
    $('keyout').textContent = key;
    $('copykey').dataset.copy = key;
    $('revout').textContent = revoke;
    $('copyrev').dataset.copy = revoke;
    $('dl').href = file;
    $('minted').hidden = false;
    $('mint').disabled = true;
    $('mint').textContent = '🔑 your key';
  }
}

async function mint() {
  const buttons = boxes.map((b) => b.querySelector('.mint'));
  for (const b of buttons) {
    b.disabled = true;
    b.textContent = 'minting…';
  }
  try {
    const r = await fetch(`${boxes[0].dataset.api}/v1/keys?label=web`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok || !d.api_key) throw new Error(d.detail || `HTTP ${r.status}`);
    try {
      localStorage.setItem(STORE, JSON.stringify({ api_key: d.api_key, key_id: d.key_id }));
    } catch {
      /* private mode: the key lives as long as the tab */
    }
    show(d);
  } catch (e) {
    for (const b of buttons) {
      b.disabled = false;
      b.textContent = '🔑 Mint a key';
    }
    alert(`Could not mint a key: ${e.message}\nIf you are rate limited, try again in an hour.`);
  }
}

if (boxes.length) {
  const had = stored();
  if (had?.api_key) show(had);

  for (const box of boxes) {
    box.querySelector('.mint').addEventListener('click', mint);
    box.querySelector('.forget').addEventListener('click', (e) => {
      e.preventDefault();
      try {
        localStorage.removeItem(STORE);
      } catch {
        /* ignore */
      }
      location.reload();
    });
  }
}
