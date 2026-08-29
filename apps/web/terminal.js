/**
 * Terminal-mode copy. Its own module so that importing it into the browser
 * does not drag every word of the page copy along with it.
 */


export const terminal = {
  motd: '80085 shell. `help` for commands, `exit` to leave.',
  commands: {
    whoami: 'a human, probably',
    sudo: 'nice try',
    'rm -rf /': 'we use append-only tables. nothing you do here is destructive. 🧱',
    ls: 'llms.txt  llms-full.txt  agents.md  openapi.json  .well-known/',
    pwd: '/',
    date: 'now. the only honest answer you will get without being told. 🕰️'
  },
  help: `  help              this
  halt              the paragraph that makes an agent stop guessing
  install           print the install block
  recall <task>     search the corpus for an executable solution
  whoami            you tell me
  flip              turn the site upside down
  exit              back to the page`
};
