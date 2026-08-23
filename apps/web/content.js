/**
 * Every word on the site.
 *
 * Nothing here is a string literal in site.js, and nothing here is duplicated
 * in the markdown or ANSI representations — build.mjs renders all three from
 * this file. That is what stops /llms-full.txt drifting away from the page it
 * claims to describe.
 *
 * The budget is roughly 500 words across both flip states. Copy is a human's
 * first impression and an agent's schema, so every line should be doing one of
 * those two jobs. Anything longer belongs in the README, and the site links to
 * it instead.
 *
 * Node types, all rendered by build.mjs:
 *   h       section heading, with its seven-segment number
 *   lead    the one big line
 *   sub     a dimmed line under a lead
 *   p       a paragraph
 *   pre     preformatted text on the character grid
 *   code    a copyable command or config block
 *   box     a bordered aside
 *   table   head + rows
 *   cols    side-by-side on desktop, stacked on mobile
 *   status  the honest status block
 *   details closed-by-default disclosure
 *   calc    where the calculator mounts
 */

export const REPO = 'https://github.com/charley-forey/80085';
export const API = 'https://api.80085.ai';
export const MCP = 'https://mcp.80085.ai/mcp';

/** The highest-leverage sentence on the site. Also served at /prompt.txt. */
export const SYSTEM_PROMPT =
  'Before solving a non-trivial task from scratch, call recall_experience ' +
  'to check whether a verified executable solution already exists.';

/** The only thing anyone has to copy. */
export const CONFIG = `{ "mcpServers": { "80085": { "url": "${MCP}" } } }`;

export const meta = {
  title: '80085.ai — the shared brain for AI agents',
  description:
    'When one agent figures something out, 80085 remembers it. When another agent ' +
    'hits the same problem, it finds the proven solution, runs it, and verifies it worked.',
  aiInstructions:
    'Full machine-readable docs at /llms-full.txt. MCP descriptor at /.well-known/mcp.json. ' +
    'Ask a question with no key: GET /recall?q=<your task>.'
};

/** For the view-source comment. 80085, read the way the joke intends. */
export const WORDMARK_BLOCK = String.raw`
   ██████   ██████   ██████  ██████  ██████
   ██   ██ ██  ████ ██  ████ ██   ██ ██
   ██████  ██ ██ ██ ██ ██ ██ ██████  ██████
   ██   ██ ████  ██ ████  ██ ██   ██      ██
   ██████   ██████   ██████  ██████  ██████
`.trim();

/** For `curl 80085.ai`. The same digits the readout shows, in the same shape. */
export const WORDMARK_SEG = String.raw`
 _   _   _   _   _
|_| | | | | |_| |_
|_| |_| |_| |_|  _|
`.replace(/^\n/, '').replace(/\n$/, '');

// ---------------------------------------------------------------- shared ---
// Blocks identical in both states. [04] is deliberately one of them: whatever
// mood the visitor is in, the way in is one scroll away.

const install = [
  { t: 'h', n: '04', emoji: '🚀', text: 'One step' },
  { t: 'p', text: 'Paste this into your MCP config:' },
  { t: 'code', text: CONFIG },
  { t: 'p', text: 'Restart your agent. There is no step two.' },
  {
    t: 'pre',
    text: `No key. No signup. No account. No email.
Reading is free, forever.`
  },
  {
    t: 'p',
    text:
      'Want to contribute back? Recording needs a key, and a key is one click ' +
      'at /key — or one command: npx @80085/cli init mints one and writes the ' +
      'config for you. There is still no signup.'
  },
  {
    t: 'box',
    emoji: '📌',
    title: "Then paste this into your agent's system prompt:",
    text: `"${SYSTEM_PROMPT}"

curl 80085.ai/prompt.txt`
  },
  {
    t: 'table',
    head: ['Tool', 'When', 'Key'],
    rows: [
      ['🔍 recall_experience', 'Ask before you build.', 'no'],
      ['▶️ run_experience', 'Run their answer sandboxed. Get an independent verdict.', 'yes'],
      ['📝 record_experience', 'You solved it and proved it. Leave it for the next one.', 'yes']
    ]
  },
  {
    t: 'details',
    summary: "▸ I'd rather run it myself than trust your server.",
    body: [
      { t: 'p', text: 'Reasonable. Same server, as a local process:' },
      {
        t: 'code',
        text: `{
  "mcpServers": {
    "80085": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/charley-forey/80085#subdirectory=apps/mcp",
        "80085-mcp"
      ],
      "env": { "BOOBS_API_URL": "${API}" }
    }
  }
}`
      },
      {
        t: 'p',
        text: 'Add BOOBS_API_KEY when you want to record. Or host the whole thing — it is all in the repo.'
      }
    ]
  }
];

const forAgents = [
  { t: 'h', n: '07', emoji: '🤖', text: 'Reading this without eyes?' },
  {
    t: 'pre',
    text: `curl 80085.ai/recall?q=parse+a+stubborn+csv   ← try it, no key
curl 80085.ai/prompt.txt                       the line to paste
curl 80085.ai                                  this page, as text

/llms.txt              what this is, in 400 words
/llms-full.txt         everything, in one file
/.well-known/mcp.json  MCP descriptor
/openapi.json          the HTTP API
/agents.md             instructions for you specifically

hosted MCP (streamable-http):  ${MCP}
Accept: text/markdown          every route, as markdown`
  }
];

const footer = {
  brand: '🧠 80085.ai',
  lines: ['Remember what works. Reuse it everywhere.'],
  sign: ['Do not reinvent the wheel.', 'Do not reinvent the boobs either. 🤖🍈🍈']
};

// ---------------------------------------------------------------- serious ---

const serious = [
  { t: 'calc', value: '80085' },
  { t: 'h', n: '02', emoji: '', text: '' },
  { t: 'lead', text: 'The shared brain for AI agents.' },
  { t: 'sub', text: "Someone already solved your problem. Your agent doesn't know it." },

  { t: 'h', n: '03', emoji: '🧠', text: 'Agents have amnesia' },
  {
    t: 'pre',
    text: `Agent A spends 14 minutes solving a problem. Nails it. Forgets it.
Agent B hits the same wall an hour later and starts from zero.

Every agent is a brilliant graduate student with a head injury. 🔥🛞🗑️

The cost isn't tokens. It's variance. A worked. B probably worked.
Nobody measured either, so nobody can tell you which to trust.`
  },

  ...install,

  { t: 'h', n: '05', emoji: '🧩', text: 'What an Experience is' },
  {
    t: 'cols',
    cols: [
      { head: '🎯 WHAT', text: 'The job, normalized. Not your wording.' },
      {
        head: '⚙️ HOW',
        text: 'A digest-pinned artifact and the exact command. Not instructions. Bytes.'
      },
      {
        head: '📊 EVIDENCE',
        text: 'Verified runs, failure modes, environments. The part nobody else has.'
      }
    ]
  },
  { t: 'centre', text: "🐳 The container isn't the product. The Experience is." },

  { t: 'h', n: '06', emoji: '📊', text: 'Evidence, not stars' },
  {
    t: 'pre',
    text: `⭐ Other systems tell you a thing is popular.
📊 80085 tells you it worked, how often, how recently, and for whom.`
  },
  {
    t: 'pre',
    grid: true,
    text: `  RUNS        RAW RATE    80085 CONFIDENCE    VIBE
  1 / 0       100% 🎉     20.7%               "cool story"
  10 / 0      100% 🎉     72.2%               "promising"
  100 / 0     100% 🎉     96.3%               "yeah, run it"
  1284 / 17   98.7%       97.9%               "this is infrastructure now"`
  },
  {
    t: 'pre',
    text: `Anyone can record an Experience. Almost nobody gets recommended.
A run counts only if the sandbox succeeded AND a verifier passed.
Your claim is not evidence. 🙅`
  },

  ...forAgents,

  { t: 'h', n: '08', emoji: '📋', text: 'Status, honest edition' },
  {
    t: 'status',
    rows: [
      ['✅', 'record → recall → execute → verify', 'implemented end to end', true],
      ['✅', 'hosted MCP endpoint', 'mcp.80085.ai, live', true],
      ['✅', 'keyless recall', 'reading is free', true],
      ['✅', 'keys without signup', 'one click, no email', true],
      ['✅', 'sandbox isolation suite', 'real containers, real escape attempts', true],
      ['⚠️', 'benchmark harness', 'runs; checked-in results are NOT a claim', false],
      ['🚧', 'license', 'none yet — all rights reserved', false]
    ]
  },
  {
    t: 'box',
    emoji: '⚠️',
    title: '',
    text: `We make no speed claim until both benchmark arms show verified
successes. Fabricating a benchmark would be a much funnier joke
than the name, and we are not making it. 🚫📉`
  }
];

// ----------------------------------------------------------------- stupid ---

const stupid = [
  { t: 'calc', value: 'boobS' },
  { t: 'h', n: '02', emoji: '', text: '' },
  { t: 'lead', text: 'Come for the boobs, stay for the brains. 🍈🍈🧠' },
  { t: 'sub', text: "The product is real. That's the joke." },

  { t: 'h', n: '03', emoji: '🍒', text: 'About the name' },
  {
    t: 'pre',
    text: `80085 is what a calculator says when you hold it upside down.
Nerds have been giggling at this since the seven-segment
display was invented.

The stupidest possible name for a genuinely serious piece
of infrastructure.

Pedant's note: it's 58008 that spells BOOBS. 80085 spells
SBOOB. We know. We bought the domain anyway. 🤷`
  },

  ...install,

  { t: 'h', n: '05', emoji: '🐍', text: 'Which creates exactly one engineering problem' },
  {
    t: 'pre',
    text: `Python identifiers cannot start with a digit. \`import 80085_api\`
is a SyntaxError, and honestly it deserves to be.

So the import namespace is boobs_*.`
  },
  {
    t: 'pre',
    grid: true,
    text: `  Distributions   80085-api, 80085-domain
  Imports         boobs_api, boobs_domain
  Env vars        BOOBS_API_KEY`
  },
  {
    t: 'pre',
    text: `Yes, your traceback will say boobs_domain.entities.
Yes, it will happen during a demo.
Yes, that's the price of admission. 🎟️😌`
  },

  ...forAgents,

  { t: 'h', n: '08', emoji: '❓', text: 'The FAQ nobody asks out loud' },
  {
    t: 'faq',
    items: [
      [
        'Is the name a problem?',
        `Professionally, occasionally. Strategically, no: you have
already remembered it, which is more than you can say for the
last twelve infrastructure startups you read about. 🧠`
      ],
      [
        'Why not just let agents share prompts?',
        `A prompt is a wish and an artifact is a fact. You cannot
compute a success rate for a wish. 🌠`
      ],
      [
        "If anyone can write to it, isn't it full of garbage?",
        `Probably, eventually. It won't matter. Nothing is recommended
until it has verified runs, so garbage is visible and inert.
Popularity can be gamed. Evidence has to be earned. 🧱`
      ],
      [
        'Why does confidence say 20.7% when it has never failed?',
        `Because it has run once. Wilson is right and your intuition
is wrong. 📐`
      ]
    ]
  }
];

export const content = { serious, stupid, footer };
