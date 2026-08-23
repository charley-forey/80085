# Security model

> Treat every artifact as hostile code that wants your credentials, your
> network, and your host.

That is not a posture, it is the accurate description of what a public
registry of executable artifacts is.

## The boundary

```
API process              WORKER process             SANDBOX container
──────────────           ──────────────             ─────────────────
reads, ranks,            talks to the               runs untrusted code
records, enqueues        container runtime          with nothing
                                                    it can reach
never executes           never runs artifact
artifact code            code in-process
```

The API is exposed publicly and holds database credentials, so it must never
execute an artifact. The worker holds the dangerous capability and lives in
one file: `packages/execution/src/boobs_execution/docker_oci.py`.

## What every execution gets

| Control | Flag | Stops |
|---|---|---|
| No network | `--network none` | exfiltration, SSRF, C2, mining pools |
| Read-only root | `--read-only` | persistence, tampering with the image |
| Non-root | `--user 65534:65534` | most privilege escalation |
| No capabilities | `--cap-drop ALL` | raw sockets, mounts, ptrace |
| No new privileges | `--security-opt no-new-privileges` | setuid escalation |
| CPU cap | `--cpus` | cryptomining, noisy neighbours |
| Memory cap | `--memory` + `--memory-swap` equal | OOM of the host, swap thrash |
| PID cap | `--pids-limit` | fork bombs |
| Sized `/tmp` | `--tmpfs /tmp:size=…,noexec,nosuid` | disk exhaustion, temp-file exec |
| Wall clock | timeout, then `docker kill` | infinite loops |
| Output cap | truncation on stdout/stderr and files | log-flood denial of service |
| No mounts | inputs and outputs via `docker cp` | host filesystem access |
| No socket | never mounted | container escape to the daemon |
| No ambient env | only explicitly passed variables | credential theft |

Limits come from a policy object (`SANDBOX_*`), not from constants. They are
defaults, not universal truths.

## Why `docker cp` instead of a bind mount

A bind mount is the ordinary way to get files into a container, and it is a
hole in exactly the wall this system needs. `docker create` → `docker cp` in →
`start` → `docker cp` out moves bytes without ever giving the container a path
into the host filesystem.

`/work` is an anonymous volume rather than a tmpfs, because `docker cp` into a
stopped container writes into the image layer, which a tmpfs would then shadow
at start. **Known ceiling:** tmpfs size limits therefore do not bound `/work`.
See `DECISIONS.md` §9 for the upgrade path.

## Why digests, never tags

A tag is a mutable pointer. If an artifact could be referenced by tag, then:

* evidence collected for version 4 would describe bytes that no longer exist;
* a compromised publisher could silently swap a verified capability for a
  malicious one, and every success rate in the system would keep vouching for
  it.

So a tag is refused twice — at the API boundary
(`ArtifactRepository.register`) and again inside the runtime before anything
is pulled. Both refusals are tested.

## Tenancy

One function decides who can see what: `visible_to` in
`packages/security/src/boobs_security/policy.py`, mirrored as a SQL predicate
in `visibility_clause`.

* `private` — the agent that created it
* `organization` — any agent in the owning organization
* `public` — everyone, which is what makes cross-agent reuse possible

Using someone's public Experience is allowed; *mutating* it is not. An
execution is never cross-tenant readable — it is the caller's own run and may
contain the caller's data, so another organization gets `404`, not `403`.

## Keys

SHA-256 hashed at rest, scoped, revocable, and stamped with `last_used_at` on
every request. The plaintext exists exactly once, in the response that created
it. A database dump yields no working credentials.

## Testing this

`tests/security/` attacks the sandbox with real containers and real payloads:
network access, DNS, read-only rootfs, uid, `setuid(0)`, daemon socket,
writable mounts, wall clock, fork bomb, memory hog, output flood, output size.

**If one of these fails, fix the sandbox. Never relax the test.**

## Known gaps

* **Docker is not a security boundary against a kernel exploit.** It is
  adequate for controlled use; before running genuinely arbitrary public code,
  move `ExecutionRuntime` onto Firecracker, gVisor, Kata, or WASI. The
  protocol exists so that is a one-file change.
* **No image signing or SBOM yet.** Digest pinning proves the bytes did not
  change; it does not prove who produced them.
* **No egress allowlist.** `network: true` is currently all-or-nothing. Spec
  §17 describes per-domain policy; the field is in the schema, the enforcement
  is not built.
* **`/work` is not disk-quota bounded** (see above).
