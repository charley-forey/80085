/**
 * Setting up a whole company, in a browser, with nobody at our end.
 *
 * /setup already told somebody to run two curl commands per colleague. That is
 * fine for one person trying it and wrong for a team lead onboarding twelve --
 * they end up tracking credentials in a spreadsheet, which is the thing you
 * least want a spreadsheet for.
 *
 * So: one button creates the organisation, and then a name at a time creates a
 * key for each person, with the config block they paste already carrying it.
 * The API endpoints are the same ones the curl commands hit; this is a front
 * end for them, not a second way of doing it.
 *
 * The founder key lives in localStorage so a return visit can keep adding
 * people. Nothing else is stored, and nothing is ever sent anywhere except the
 * two API calls a visitor explicitly clicks.
 */

const panel = document.querySelector('.teamsetup');
if (panel) {
  const API = panel.dataset.api;
  const MCP = panel.dataset.mcp;
  const STORE = '80085.org';

  const $ = (cls) => panel.querySelector(`.${cls}`);
  const read = () => {
    try {
      return JSON.parse(localStorage.getItem(STORE) || 'null');
    } catch {
      return null;
    }
  };

  /* Everything a person needs, in the form they will paste it. Written as a
     file too: there is no account, so this download is the only recovery. */
  const configFor = (name, key) =>
    `# ${name}\n\n` +
    `claude mcp add --transport http 80085 ${MCP} \\\n` +
    `  --header "Authorization: Bearer ${key}"\n\n` +
    `# or, for Cursor / Windsurf / Claude Desktop:\n` +
    `{ "mcpServers": { "80085": {\n` +
    `    "url": "${MCP}",\n` +
    `    "headers": { "Authorization": "Bearer ${key}" } } } }\n`;

  const people = [];

  function addRow(name, key) {
    people.push({ name, key });
    const row = document.createElement('div');
    row.className = 'person';
    row.innerHTML =
      `<div class="who">${name.replace(/[<&]/g, '')}</div>` +
      `<pre class="cfg"></pre>` +
      `<button class="copy" type="button">copy</button>`;
    row.querySelector('.cfg').textContent = configFor(name, key);
    row.querySelector('.copy').addEventListener('click', () => {
      navigator.clipboard.writeText(configFor(name, key));
      row.querySelector('.copy').textContent = 'copied';
    });
    $('people').appendChild(row);
    $('bulk').hidden = false;
    $('bulk').href =
      'data:text/plain;charset=utf-8,' +
      encodeURIComponent(
        `80085 — keys for your team\n\nThere is no account. This file is the ` +
          `recovery.\nOne key per person. Never share one between people: everything ` +
          `they\nask and answer is attributed to whoever the key belongs to.\n\n` +
          people.map((p) => configFor(p.name, p.key)).join('\n')
      );
  }

  function organised(org) {
    localStorage.setItem(STORE, JSON.stringify(org));
    $('step1').hidden = true;
    $('step2').hidden = false;
    $('orgid').textContent = org.organization_id;
    $('founder').textContent = org.api_key;
    $('copyfounder').addEventListener('click', () => {
      navigator.clipboard.writeText(org.api_key);
      $('copyfounder').textContent = 'copied';
    });
    $('savefounder').href =
      'data:text/plain;charset=utf-8,' +
      encodeURIComponent(
        `80085 founder key\n\n${org.api_key}\n\norganization: ${org.organization_id}\n\n` +
          `This is the only key that can issue more. There is no account and we\n` +
          `cannot send it to you again. Store it where you keep other root\n` +
          `credentials.\n`
      );
  }

  const existing = read();
  if (existing) organised(existing);

  $('create').addEventListener('click', async () => {
    const name = ($('orgname').value || 'my-team').trim().slice(0, 60);
    const button = $('create');
    button.disabled = true;
    button.textContent = 'creating…';
    try {
      const res = await fetch(`${API}/v1/keys?label=${encodeURIComponent(name)}`, {
        method: 'POST'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      organised(await res.json());
    } catch (err) {
      button.disabled = false;
      button.textContent = 'create my organisation';
      $('err').textContent = `Could not create it: ${err.message}. Five an hour per address.`;
    }
  });

  $('add').addEventListener('click', async () => {
    const org = read();
    const name = ($('person').value || '').trim().slice(0, 60);
    if (!org || !name) return;
    const button = $('add');
    button.disabled = true;
    try {
      const res = await fetch(`${API}/v1/agents`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${org.api_key}`
        },
        body: JSON.stringify({ name })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const made = await res.json();
      addRow(name, made.api_key);
      $('person').value = '';
      $('err').textContent = '';
    } catch (err) {
      $('err').textContent = `Could not add ${name}: ${err.message}`;
    } finally {
      button.disabled = false;
    }
  });

  $('person').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('add').click();
  });
}
