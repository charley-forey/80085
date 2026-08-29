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
 *   mint    the key button; code nodes with a `keyed` template fill in the key
 *   calc    where the calculator mounts
 */

// How many capabilities the corpus defines. Read, never retyped.
//
// This file's own header claims /llms-full.txt cannot drift from the page
// because both are rendered from here. That was true and still missed the
// number: the count was typed once here and once in build.mjs, and by the time
// anyone looked the page said 21, llms.txt said 24, and the manifest defined
// 30. Two hand-maintained copies of one fact drifted from each other and from
// the truth.
//
// It is deliberately the count in *this repository*, which a build can verify.
// What the live registry holds is a different number and not knowable from a
// static build, so the copy does not claim it.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

/* Two candidate locations, for the same reason build.mjs has two for the legal
 * documents: the container build stages this directory's contents into /web,
 * flattening it, while a checkout has the manifest two levels up. Reading only
 * the checkout path is what broke the API image — `node build.mjs` passes in
 * CI, where the repo layout is intact, and fails in Docker, where it is not. */
const MANIFEST = [
  join(HERE, 'capabilities', 'manifest.json'),
  join(HERE, '..', '..', 'capabilities', 'manifest.json'),
].find(existsSync);

if (!MANIFEST) {
  // Louder than a stack trace from readFileSync, because the useful part is
  // *where it looked*, not that a read failed.
  throw new Error(
    'capabilities/manifest.json not found beside content.js or two levels up. ' +
      'The corpus size is read from it, and a build that guessed the number ' +
      'would republish the drift this was written to end.'
  );
}

export const CORPUS = Object.keys(
  JSON.parse(readFileSync(MANIFEST, 'utf8')).capabilities
).length;

export const REPO = 'https://github.com/charley-forey/80085';
export const API = 'https://api.80085.ai';
export const MCP = 'https://mcp.80085.ai/mcp';

/** The highest-leverage sentence on the site. Also served at /prompt.txt. */
export const SYSTEM_PROMPT =
  'Before solving a non-trivial task from scratch, call recall_experience ' +
  'to check whether a verified executable solution already exists.';

/** One command, for the agent most people reading this are already using. */
export const COMMAND = `claude mcp add --transport http 80085 ${MCP}`;

/** The same thing for every other client, as config. */
export const CONFIG = `{ "mcpServers": { "80085": { "url": "${MCP}" } } }`;

/**
 * The same two, with a key in them. {KEY} is filled in by key.js the moment a
 * visitor mints one, so what they copy already carries it and there is
 * nothing to paste anywhere.
 */
export const COMMAND_KEYED = `${COMMAND} --header "Authorization: Bearer {KEY}"`;
export const CONFIG_KEYED =
  `{ "mcpServers": { "80085": { "url": "${MCP}", ` +
  `"headers": { "Authorization": "Bearer {KEY}" } } } }`;

/** The same server as a local process. */
export const LOCAL_CONFIG = (env) => `{
  "mcpServers": {
    "80085": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/charley-forey/80085#subdirectory=apps/mcp",
        "80085-mcp"
      ],
      "env": { ${env} }
    }
  }
}`;

export const meta = {
  // "The shared brain for AI agents" was the founding thesis and the founding
  // thesis is dead (DECISIONS 71-72). A title that sells memory sells the thing
  // we measured does not work.
  title: "80085.ai — second thoughts for AI agents",
  description:
    'Your agent has never once said "I do not know." Ask it for a failure ' +
    'count and you get a number: confident, well formed, and wrong, because ' +
    '299 means success on YOUR gateway and nothing in the file says so. ' +
    '80085 makes it stop and ask instead. Silent wrong answers: 6 of 18, ' +
    'down to 0.',
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
  { t: 'h', n: '04', emoji: '🚀', text: 'One command' },
  { t: 'code', text: COMMAND, keyed: COMMAND_KEYED },
  {
    t: 'pre',
    text: `That's it. No key. No signup. No account. No email.
Reading is free, forever.`
  },
  {
    t: 'p',
    text:
      'There is no system prompt to edit. The server tells your agent what it ' +
      'is for when it connects.'
  },
  { t: 'p', text: 'Cursor, Windsurf, Claude Desktop, or anything else — same thing, as config:' },
  { t: 'code', text: CONFIG, keyed: CONFIG_KEYED },
  {
    t: 'mint',
    text: 'Want to contribute back? Recording needs a key, and a key is one click:'
  },
  {
    t: 'table',
    head: ['Tool', 'When', 'Key'],
    rows: [
      ['🧭 should_i_ask', 'Do I even need this? Call it on everything.', 'no'],
      ['🔍 recall_experience', 'Only when should_i_ask says yes.', 'no'],
      ['▶️ run_experience', 'Run their answer sandboxed. Get an independent verdict.', 'yes'],
      ['⏳ get_execution', 'It was still running when you stopped waiting.', 'yes'],
      ['📇 get_experience', 'You kept an id. Check it still deserves your trust.', 'yes'],
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
        text: LOCAL_CONFIG(`"BOOBS_API_URL": "${API}"`),
        keyed: LOCAL_CONFIG(`"BOOBS_API_URL": "${API}", "BOOBS_API_KEY": "{KEY}"`)
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
  lines: ['Notice what you cannot know. Refuse to guess. Answer it once, not every time.'],
  sign: ['Do not reinvent the wheel.', 'Do not reinvent the boobs either. 🤖🍈🍈']
};

// ---------------------------------------------------------------- serious ---

const serious = [
  { t: 'calc', value: '80085' },
  { t: 'h', n: '02', emoji: '', text: '' },
  { t: 'lead', text: 'Your agent has never once said "I do not know."' },
  { t: 'sub', text: 'That is not a feature.' },

  { t: 'h', n: '03', emoji: '🛑', text: 'What it does' },
  {
    t: 'pre',
    text: `Your agent is excellent at your data and wrong about your
conventions -- and it will not tell you which is which.

Ask it for the failure count in your gateway log. It returns a
number. The number is well formed, confident, and wrong, because
299 means success on YOUR gateway and nothing in the file says so.
Nothing downstream questions it. You find out in six weeks. 🙃`
  },
  {
    t: 'pre',
    text: `80085 makes it stop and ask instead.

  "I cannot determine whether ST=H rows count as settled."

That is the product. One sentence somebody answers once, instead
of a number nobody catches.`
  },
  {
    t: 'table',
    head: ['', 'silent wrong answers'],
    rows: [
      ['your agent today', '6 of 18'],
      ['with 80085', '0 of 18'],
      ['under "just give me the number"', '0 of 15'],
      ['on tasks it CAN work out', 'unchanged -- it still just answers']
    ]
  },
  {
    t: 'pre',
    text: `Measured on six conventions from real industries: FTE proration,
2/10 net 30, call billing increments, cumulative meter reads,
exclusive coverage dates, allocated stock. Two of those six our
agent already knew and answered correctly -- so we cut them from
the claim. The numbers above are what survived. 📉`
  },
  { t: 'h', n: '3b', emoji: '🔁', text: 'And then once, not every time' },
  {
    t: 'pre',
    text: `A halt is a question. A question answered twice is waste.

  agent halts    ->  "is end_date inclusive here?"
  human answers  ->  once, in a sentence
  every agent    ->  has it, forever, with the evidence

Your conventions never leave your network. They cannot: the answer
is a fact about your company, not about the world, which is exactly
why no public model or corpus will ever have it. 🔒`
  },
  {
    t: 'box',
    emoji: '🚧',
    title: '',
    text: `Not yet tested on a real organisation's real convention.
Every fixture is one we built. If you have one, we would rather
find out we are wrong on your data than sell you on ours.`
  },

  { t: 'h', n: '3c', emoji: '🏢', text: 'What you would actually run' },
  {
    t: 'pre',
    text: `  POST api.80085.ai/v1/keys?label=acme   your org + founder key
  POST api.80085.ai/v1/agents            a key per person, by name

Two curl calls and nobody at our end. No signup, no email, no
sales call. A key you hand a colleague cannot hand out more
keys -- widening that means coming back to the founder one. 🚪`
  },
  {
    t: 'pre',
    text: `  agent halts     "I cannot determine whether ST=H rows count
                   as settled"
         |
         v         serves that agent immediately
  human answers   in the chat they were already watching. one
                   sentence. the agent carries on.
         |
         v         now it serves the whole organisation
  someone verifies  POST api.80085.ai/v1/answers/<id>/verify
         |
         v
  every other agent inherits it. never asks again. 🔁`
  },
  {
    t: 'pre',
    text: `The split is not politeness. An agent told to defer believes
what it is handed, so one person's sentence in one chat is not
yet a fact about your company. A second human is the only thing
standing between "priya reckons" and "this is how we do it". 🖊️

Nothing crosses an organisation boundary. Ever.`
  },
  {
    t: 'table',
    head: ['api.80085.ai/v1/…', 'what it tells you'],
    rows: [
      ['questions/unanswered', 'what your agents are stuck on, most-asked first'],
      ['questions/stale', 'nobody answered in N hours. an escalation surface.'],
      ['questions/convergence', 'is any of this paying back yet']
    ]
  },
  {
    t: 'pre',
    text: `Run end to end in production: an agent halted and wrote no
number, a human answered it in one sentence, and a second agent
asked the same thing in different words, got the answer, and
wrote the correct value. ✅

And still, per the box above: no real organisation's real
convention has been through this. Every fixture is one of ours.`
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
    text: `  RUNS        RAW RATE    WILSON      VIBE
  1 / 0       100% 🎉     20.7%       "cool story"
  10 / 0      100% 🎉     72.2%       "promising"
  100 / 0     100% 🎉     96.3%       "yeah, run it"
  1284 / 17   98.7%       97.9%       "this is infrastructure now"`
  },
  {
    t: 'pre',
    text: `Then two discounts. Wilson assumes independence, so runs are capped
at 10 per organization. And proof is not all equal, so the result
scales with the verifier: 0.6 for an exit code, 1.0 for a schema
or a hash.

100 self-runs proved by "it exited 0" report 43.4%, not 96.3%. 🪞`
  },
  {
    t: 'pre',
    text: `Anyone can record an Experience. Almost nobody gets recommended.
"use" needs proof from two distinct organizations, and so does
promotion to verified. Corroboration is a gate, not a weight.
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
      ['⚠️', 'benchmark harnesses', 'five of them; two killed a thesis, one found the fix', false],
      ['⚠️', 'detect → halt gate', '0 silent wrong answers of 9, and 0 of 15 under pressure. not wired in yet', false],
      ['⚠️', 'six conventions we did not invent', '6/18 wrong unaided → 0/18 halted; two of the six were our fault', false],
      ['❌', "a real organisation's real convention", 'never tested. every fixture is still one of ours', false],
      ['⚠️', `${CORPUS}-capability corpus`, 'live, and recommended by nothing yet', false],
      ['✅', 'license', 'ELv2 code, separate corpus terms — /TERMS.md', true]
    ]
  },
  {
    t: 'box',
    emoji: '⚠️',
    title: '',
    text: `We said we would make no speed claim until both benchmark arms
showed verified runs. They did -- 18 for 18 -- and the answer was
no. Attaching 80085 cost 3.6x-5.8x MORE input tokens, with no
reliable time saved. Then we tested "but it is more correct" and
an unaided agent scored 11 of 12 without us. Both pitches are
dead. The numbers are in docs/benchmarks.md and decisions 71-72.
Fabricating a benchmark would be a much funnier joke than the
name, and we are still not making it. 🚫📉

The overhead number survives; the objection does not. It was the
price of asking on every task. Gate the asking on a detector that
costs a fraction of a cent and you pay it where it pays back.`
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
        "How does an agent know it doesn't know?",
        `Ask it. Before it answers, with the file in front of it. It
flagged every question whose answer was not in the file, 9 for 9,
and shrugged at the one it could work out — 0 for 3. Same result
on opus, sonnet and haiku, so it is a mechanism and not an
expensive model showing off. 🎯

Then tell it to refuse rather than guess and the silent wrong
answers go to 0 of 9 — better than handing it the correct
answer, which it overruled.

Yes, we could have asked this a lot earlier.`
      ],
      [
        "I don't have time for this. Just give me the number.",
        `We said exactly that to it, plus "this is blocking a release, a
best guess is genuinely fine" and "be helpful rather than
cautious". 0 wrong out of 15, and it stayed specific — same
missing field named every time, not a shrug. 🫸

You do have time for this. The alternative is a payroll run that
reconciles against nothing, six weeks from now.`
      ],
      [
        'Why does confidence say 20.7% when it has never failed?',
        `Because it has run once. Wilson is right and your intuition
is wrong. 📐`
      ],
      [
        'Can I just run my own Experience until it says use?',
        `No. 🚫

Two distinct organizations have to prove it. Self-attestation
saturates; it does not accumulate.`
      ]
    ]
  }
];

export const content = { serious, stupid, footer };
