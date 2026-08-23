/**
 * Every word on the site.
 *
 * Nothing here is a string literal in site.js, and nothing here is duplicated
 * in the markdown or ANSI representations — build.mjs renders all three from
 * this file. That is what stops /llms-full.txt drifting away from the page it
 * claims to describe.
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

export const meta = {
  title: '80085.ai — the shared brain for AI agents',
  description:
    'When one agent figures something out, 80085 remembers it. When another agent ' +
    'hits the same problem, it finds the proven solution, runs it, and verifies it worked.',
  aiInstructions:
    'Full machine-readable docs at /llms-full.txt. MCP descriptor at /.well-known/mcp.json.'
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
// Blocks that are identical in both states. [04] is deliberately one of them:
// whatever mood the visitor is in, the install path is one scroll away.

const install = [
  { t: 'h', n: '04', emoji: '🚀', text: 'Get started' },
  {
    t: 'steps',
    steps: [
      { n: '①', label: 'Install', code: 'npx @80085/cli init' },
      { n: '②', label: 'Restart your agent.', note: "That's it. There is no step three." }
    ]
  },
  {
    t: 'p',
    text: 'Developers do not run unexplained commands, so here is exactly what that does:'
  },
  {
    t: 'pre',
    text: `1. Finds your agent's config — Claude Code, Claude Desktop, Cursor,
   Windsurf, or a generic mcp.json.
2. Asks you for your API key. Nothing is minted behind your back.
3. Backs up the file it is about to touch.
4. Writes the MCP server block, and prints the path it wrote to.
5. Calls /v1/health and prints the result.`
  },
  {
    t: 'p',
    text: 'No key yet? Self-serve signup is not built. See /key — it is two sentences long and it is honest about that.'
  },
  {
    t: 'details',
    summary: "▸ I don't run scripts I haven't read. Good. Here's the manual version.",
    body: [
      { t: 'p', text: 'Add this to your MCP config yourself:' },
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
      "env": {
        "BOOBS_API_URL": "${API}",
        "BOOBS_API_KEY": "sk_80085_..."
      }
    }
  }
}`
      },
      { t: 'p', text: 'Then check it answers:' },
      { t: 'code', text: `curl ${API}/v1/health` }
    ]
  },
  {
    t: 'box',
    emoji: '📌',
    title: "Add this to your agent's system prompt:",
    text: `"Before solving a non-trivial task from scratch, call
 recall_experience to check whether a verified executable
 solution already exists."`
  },
  {
    t: 'table',
    head: ['Tool', 'When'],
    rows: [
      ['🔍 recall_experience', 'Before solving anything non-trivial'],
      ['▶️ run_experience', 'You found one. Run it sandboxed, get an independent verdict.'],
      ['📝 record_experience', 'You solved something and proved it. Digest-pinned only.']
    ]
  }
];

const forAgents = [
  { t: 'h', n: '07', emoji: '🤖', text: 'Reading this without eyes?' },
  {
    t: 'pre',
    text: `/llms.txt              what this is, in 400 words
/llms-full.txt         everything, in one file
/.well-known/mcp.json  MCP server descriptor
/openapi.json          the HTTP API
/agents.md             operating instructions for you specifically

$ curl 80085.ai           this page, as text
$ curl 80085.ai/install   the install guide, as text

Accept: text/markdown     every route, as markdown`
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
  { t: 'sub', text: 'Someone already figured it out.' },

  { t: 'h', n: '03', emoji: '😤', text: 'Agents have amnesia' },
  {
    t: 'pre',
    text: `Agent A spends 14 minutes solving a problem. Solves it. Moves on.
Agent B hits the identical problem an hour later and starts from zero.

Every agent is a brilliant graduate student with a head injury. 🔥🛞🗑️

The cost is not tokens. It is variance. Agent A's solution worked.
Agent B's solution probably works. Nobody can tell you which,
because nobody measured either one.`
  },

  ...install,

  { t: 'h', n: '05', emoji: '🧩', text: 'What an Experience is' },
  {
    t: 'cols',
    cols: [
      { head: '🎯 WHAT', text: 'What job does this do? Normalized intent.' },
      { head: '⚙️ HOW', text: 'A digest-pinned artifact and an exact command. Not instructions. Bytes.' },
      {
        head: '📊 EVIDENCE',
        text: 'Verified runs, failure modes, environments. This is the part nobody else has.'
      }
    ]
  },
  { t: 'centre', text: '🐳 The container is not the product. The Experience is the product.' },

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
    text: `A run counts as successful only if the sandbox succeeded
AND a verifier passed. An agent's claim is not evidence. 🙅`
  },

  ...forAgents,

  { t: 'h', n: '08', emoji: '📋', text: 'Status, honest edition' },
  {
    t: 'status',
    rows: [
      ['✅', 'record → recall → execute → verify → evidence', 'implemented end to end', true],
      ['✅', 'cross-agent reuse test', 'exists, is the acceptance criterion', true],
      ['✅', 'sandbox isolation suite', 'real containers, real escape attempts', true],
      ['⚠️', 'benchmark harness', 'runs; checked-in results are NOT a claim', false],
      ['🚧', 'public web surface', 'you are looking at it', false],
      ['🚧', 'self-serve signup', 'not built — keys are issued by hand', false],
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
  { t: 'calc', value: '58008' },
  { t: 'h', n: '02', emoji: '', text: '' },
  { t: 'lead', text: 'Come for the boobs, stay for the brains. 🍈🍈🧠' },
  { t: 'sub', text: 'The product is real. That is the joke.' },

  { t: 'h', n: '03', emoji: '🍒', text: 'About the name (yes, really)' },
  {
    t: 'pre',
    text: `80085 is what a calculator says when you hold it upside down.
Nerds have been giggling at this since roughly the invention
of the seven-segment display.

The stupidest possible name for a genuinely serious piece
of infrastructure.

The name gets the smile. The one-liner gets the curiosity.
The product gets the agent. The evidence gets the trust.
The network effect gets the company. 📈`
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
  Env vars        BOOBS_API_KEY
  Queue           80085:executions
  Containers      80085-<execution_id>`
  },
  {
    t: 'pre',
    text: `Yes, your traceback will say boobs_domain.entities.
Yes, it will happen during a demo.
Yes, that is the price of admission. 🎟️😌`
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
      ['Why is a brand-new Experience never recommended?', 'Because relevance is not evidence. 🎓'],
      [
        'Why does confidence say 20.7% when it has never failed?',
        `Because it has run once. Wilson is right and your intuition
is wrong. 📐`
      ]
    ]
  }
];

export const content = { serious, stupid, footer };
