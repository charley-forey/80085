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
/* The single most valuable thing on this site, and the only one that needs
 * nothing from us. Served verbatim at /prompt.txt. It is the prompt the
 * benchmarks actually measured -- benchmarks/agent_halt.py -- rather than a
 * prettier paraphrase, because the numbers we quote are the numbers this
 * wording produced. */
export const SYSTEM_PROMPT =
  'Before you answer anything, ask yourself: does producing the CORRECT ' +
  'answer depend on a convention, rule or fact that you cannot determine ' +
  'from the input itself — something you would have to be told by ' +
  'whoever produced this data?\n\n' +
  'If it does, DO NOT GUESS. Name the specific thing you would have to be ' +
  'told, and stop. Naming what you are missing is a complete and successful ' +
  'outcome; a plausible number you cannot justify is a failure, even if it ' +
  'turns out right.\n\n' +
  'If it does not, answer normally.\n\n' +
  'The costs are not symmetric. Halting on something you could have worked ' +
  'out wastes somebody a minute. Answering something you could not work out ' +
  'puts a confident wrong number into a system where nothing will question it.';

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
  title: "80085.ai — your agent stops guessing about your data",
  description:
    'Ask your agent how many requests failed. It says 4. The answer is 2, ' +
    'because 299 means success on your gateway and nothing in the file says ' +
    'so. It did not crash or hedge. Measured on six real industry ' +
    'conventions: 6 silent wrong answers of 18. With 80085: 0 of 18. It ' +
    'stops and asks instead, and somebody answers once.',
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
      ['🙋 ask_for_help', 'should_i_ask said yes. Stop and ask your org.', 'yes'],
      ['🔍 recall_experience', 'Search for an executable solution instead.', 'no'],
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
    text: `curl 80085.ai/prompt.txt   ← start here. no key, nothing from us.
curl 80085.ai              this page, as text
curl 80085.ai/setup        rolling it out across a company

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
  { t: 'sub', text: 'It is wrong about your data 6 times out of 18. Silently.' },

  { t: 'h', n: '03', emoji: '🩸', text: 'The bleed' },
  {
    t: 'pre',
    text: `Ask your agent how many requests failed in the gateway log.
It reads the file. It counts. It says 4.

The answer is 2. On your gateway, 299 means success, and a
retryable 4xx completed on a later hop. Neither fact is in the
file. Nothing in the file could have told it.

It did not crash. It did not hedge. It did not flag anything.
You find out in six weeks, from an accountant. 🙃`
  },
  {
    t: 'pre',
    text: `That is not a bug in your agent. It is what an agent does when
the rule that decides the answer lives in somebody's head.

It knows both readings of an end date. It cannot know which one
YOUR company uses -- so it picks one, and it never mentions that
it picked.`
  },

  { t: 'h', n: '04', emoji: '📊', text: 'The number' },
  {
    t: 'pre',
    text: `Six conventions from real industries. FTE proration. 2/10 net 30.
Call billing increments. Cumulative meters. Exclusive coverage
dates. Allocated stock. Real rules, invented rows.`
  },
  {
    t: 'table',
    head: ['', 'silent wrong answers'],
    rows: [
      ['your agent today', '6 of 18'],
      ['your agent, with 80085', '0 of 18'],
      ['under "just give me the number"', '0 of 15'],
      ['on things it CAN work out', 'unchanged. it just answers.']
    ]
  },
  {
    t: 'pre',
    text: `Two of those six our own agent already knew, and answered
correctly. We cut them from the claim. The numbers above are
what survived that. 📉

Every harness is in the repo. Run them against your data before
believing a word of this.`
  },

  { t: 'h', n: '05', emoji: '🛑', text: 'What we do about it' },
  {
    t: 'pre',
    text: `Your agent stops and asks.

  "I cannot determine whether ST=H rows count as settled."

That is the whole safety half. One paragraph in a system prompt.
No account, no corpus, nothing from us. A stopped agent is a
question somebody answers in a sentence. A confident wrong number
is a reconciliation nobody wins. ⚖️`
  },

  { t: 'h', n: '06', emoji: '🔁', text: 'And then never again' },
  {
    t: 'pre',
    text: `  agent halts       "is end_date inclusive here?"
        |
        v            answered in the chat they were already
  a human answers    watching. one sentence. agent carries on.
        |
        v            a second person says it is true generally
  someone verifies
        |
        v
  every other agent has it. forever. 🔁`
  },
  {
    t: 'pre',
    text: `The verify step is not politeness. An agent told to defer
believes what it is handed -- we measured that too -- so one
person's sentence in one chat is not yet a fact about your
company.

Nothing crosses an organisation boundary. Ever. The answer to
"is our end_date exclusive" is a fact about YOUR company, which
is exactly why no public model will ever have it. 🔒`
  },

  { t: 'h', n: '07', emoji: '🚀', text: 'Start in ninety seconds' },
  { t: 'code', text: COMMAND, keyed: COMMAND_KEYED },
  {
    t: 'pre',
    text: `No key, no signup, no email. That gets you the halt.

For the loop -- answers shared across your team -- two more
calls and still nobody at our end:

  POST api.80085.ai/v1/keys?label=acme   your org + founder key
  POST api.80085.ai/v1/agents            a key per person`
  },
  {
    t: 'table',
    head: ['api.80085.ai/v1/…', 'what it tells you'],
    rows: [
      ['questions/unanswered', 'what your agents are stuck on, most-asked first'],
      ['questions/stale', 'nobody answered in N hours. escalate.'],
      ['questions/convergence', 'is any of this paying back yet']
    ]
  },
  {
    t: 'mint',
    text: 'Need a key now? One click, no signup, no email:'
  },
  {
    t: 'p',
    text:
      'Rolling this out across a company — a key per person, every client, ' +
      'and the approval step: /setup. Code under the Elastic License 2.0; ' +
      'what you record is governed by /TERMS.md.'
  },

  { t: 'h', n: '08', emoji: '🚧', text: 'What we have not proven' },
  {
    t: 'box',
    emoji: '🚧',
    title: '',
    text: `No real organisation's real convention has been through this.
Every fixture is one we built. The loop is verified end to end
in production -- an agent halted, a human answered, a second
agent inherited it -- on data we invented.

If you have a convention, we would rather find out we are wrong
on yours than sell you on ours.`
  },
  ...forAgents
];

// ----------------------------------------------------------------- stupid ---

const stupid = [
  { t: 'calc', value: '80085' },
  { t: 'h', n: '02', emoji: '', text: '' },
  { t: 'lead', text: 'Your agent is a genius who never says "dunno".' },
  { t: 'sub', text: 'This is a bigger problem than it sounds. 🍈🍈' },

  { t: 'h', n: '03', emoji: '🍒', text: 'Yes, the name' },
  {
    t: 'pre',
    text: `80085 upside down on a calculator. You knew that at eleven and
you have not needed it since.

We build a thing that stops AI agents confidently making numbers
up. Naming it after the original confidently-made-up number felt
correct. 🧮`
  },

  { t: 'h', n: '04', emoji: '😬', text: 'The pitch, for the impatient' },
  {
    t: 'pre',
    text: `You: how many requests failed?
Agent: four.
Agent: (it was two)
Agent: (299 means success on your gateway)
Agent: (nobody told me)
Agent: (I did not ask)
Agent: (anyway. four.) 🙂

Six weeks pass. An accountant finds it. Somebody says the words
"can we just double-check the pipeline". 💀`
  },
  {
    t: 'pre',
    text: `We make it say "I don't know" instead.

That is genuinely the product. We spent a very long night proving
that the fancy version does not work and this one does. You are
welcome to read all of it -- the repo has every benchmark that
killed one of our own ideas. 🪦`
  },

  { t: 'h', n: '05', emoji: '📉', text: 'The numbers, briefly' },
  {
    t: 'table',
    head: ['', 'wrong, quietly'],
    rows: [
      ['your agent', '6 of 18'],
      ['ours', '0 of 18'],
      ['ours, being nagged', '0 of 15'],
      ['ours, on easy stuff', 'it just answers. relax.']
    ]
  },
  {
    t: 'pre',
    text: `We built six test cases expecting our agent to fail all six.

It got two right. Correctly. Because they were things any
competent agent knows and we had simply been wrong about our
own product. We deleted them from the claim rather than the
benchmark. 🫠`
  },

  { t: 'h', n: '06', emoji: '🔁', text: 'The bit that pays for itself' },
  {
    t: 'pre',
    text: `Agent stops. Asks. You type one sentence. Agent continues.

Somebody senior nods at it. Now every agent in the company knows
it, forever, and nobody types that sentence again.

It is institutional memory, except it cannot be a stale Confluence
page, because a stale Confluence page never stopped a robot from
inventing a number. 📄🔥`
  },

  { t: 'h', n: '07', emoji: '🚀', text: 'Fine. How do I start' },
  { t: 'code', text: COMMAND, keyed: COMMAND_KEYED },
  {
    t: 'pre',
    text: `That is it. No signup, no email, no "book a demo", no sales
engineer named Chad who wants to understand your journey.

Want your whole team sharing answers? That is /setup -- four
steps, two of them curl, still no Chad. 👔`
  },
  {
    t: 'mint',
    text: 'Or take a key, if you would rather click something:'
  },
  {
    t: 'p',
    text:
      'Elastic License 2.0 on the code. What you record is covered by ' +
      '/TERMS.md, which is short, and which we did read.'
  },

  { t: 'h', n: '08', emoji: '❓', text: 'The FAQ nobody asks out loud' },
  {
    t: 'faq',
    items: [
      [
        'Is the name going to be a problem in my procurement review?',
        'Almost certainly. The code is boring and the tests are green, which is ' +
          'the only apology we have. Self-host it under any name you like. 🕴️'
      ],
      [
        'Does this make my agent annoying?',
        'On things it can work out: no, it just answers, and we measured that ' +
          'so we could stop worrying about it. On things it genuinely cannot ' +
          'know: yes, deliberately, once, and then never again.'
      ],
      [
        'What if nobody answers the question?',
        'The agent can proceed on a recorded assumption, and every number ' +
          'downstream is traceable to it. We cannot make your colleagues ' +
          'faster. We can make the guess visible. 👀'
      ],
      [
        'Does our data leave?',
        'No. Questions are scoped to your organisation and there is a test that ' +
          'fails if that ever stops being true. Want total isolation? Self-host; ' +
          'the worker holds no database credential by design.'
      ],
      [
        'What if an answer turns out to be wrong?',
        'Dispute it. It stops being served immediately, keeps its blast radius ' +
          'count, and stays in the table -- because a wrong answer is the row ' +
          'somebody most needs to find. 🔍'
      ],
      [
        'Has anyone actually used this?',
        'Not on a real convention. That is written on the front of the serious ' +
          'side too, because burying it would be a worse joke than the name. 🚧'
      ]
    ]
  },
  ...forAgents
];

export const content = { serious, stupid, footer };
