# Contributing to 80085.ai

Contributions are welcome — issues, fixes, new capabilities, better evidence.
Read this first; it is short and it is binding.

## Inbound licence (important)

**By opening a pull request or submitting a capability, you agree to the terms
below.** There is no separate form to sign.

You grant 80085.ai a **perpetual, irrevocable, worldwide, royalty-free,
sublicensable and transferable licence** to use, reproduce, modify, adapt,
publish, distribute and relicense your contribution, as part of this project or
any successor, under any licence — including commercial and proprietary terms.

You retain copyright in your contribution. You are not assigning ownership; you
are granting us rights broad enough that we can keep the project licensable as a
whole.

You confirm that:

- the contribution is your own work, or you have the right to submit it;
- your employer, if they have a claim to it, permits the contribution;
- it contains no secrets, credentials, personal data, or third-party code you
  cannot license under these terms;
- it is offered under the same terms as this project's [`LICENSE`](LICENSE).

**Why this exists:** without a clear inbound grant, a project with many
contributors cannot change its licence, offer commercial terms, or defend
itself, because no single party holds sufficient rights. This clause keeps those
options open. If you are not comfortable granting it, please open an issue
describing the fix instead of a PR, and we will implement it independently.

## Submitting capabilities

Capabilities submitted through the API or MCP endpoint are covered by
[`TERMS.md`](TERMS.md) §6, which carries the same grant.

A good capability:

- does one thing, and does it deterministically;
- runs in the sandbox — no network, no root, read-only filesystem;
- declares its inputs and outputs honestly;
- ships with at least one runnable check that fails if the logic breaks.

## Pull requests

- Keep the diff small and the intent obvious.
- Match the surrounding code — naming, comment density, idiom.
- Run `make test` (or `pytest`) before opening.
- Explain *why*, not *what*; the diff already says what.

## What we will not merge

- Anything that weakens the execution sandbox.
- Anything that logs, exfiltrates, or widens access to corpus data.
- Speculative abstraction with no current caller.
- Vendored code with an incompatible licence.

## Security

Do not open a public issue for a security problem — especially sandbox escapes.
Contact the maintainers privately via the repository first.
